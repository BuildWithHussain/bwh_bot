# Copyright (c) 2026, BWH Studios and Contributors
# See license.txt
"""Tests for the /hive conversation and its remote Hive client.

Both the Telegram transport and the remote HTTP calls are patched out, so these
run on any site: the bot never needs Hive installed alongside it.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from bwh_bot import hive_client
from bwh_bot.handlers.hive import DEFAULT_STATUS, HiveTaskConversation
from bwh_bot.hive_client import HiveSiteError

CHAT_ID = 987001
TG_USER_ID = 424242

PROJECTS = [
	{"name": "PROJ-00001", "title": "Apollo"},
	{"name": "PROJ-00002", "title": "Borealis"},
]
MEMBERS = [
	{"user": "ada@example.com", "member_name": "Ada"},
	{"user": "grace@example.com", "member_name": "Grace"},
]


class FakeSite:
	"""Stands in for a BWH Bot Hive Site child row."""

	def __init__(self, name="row1", label="Hive", url="https://hive.example.com", is_active=1):
		self.name = name
		self.label = label
		self.site_url = url
		self.api_key = "key"
		self.is_active = is_active


def _command_message(chat_id=CHAT_ID, user_id=TG_USER_ID):
	return {"chat": {"id": chat_id}, "message_id": 1, "from": {"id": user_id}}


class HiveConversationTestCase(IntegrationTestCase):
	"""Shared harness: Telegram calls captured, remote client stubbed."""

	sites = None

	def setUp(self):
		self.sites = self.sites or [FakeSite()]
		self.created = []
		self.assigned = []
		self.sent = []
		self.markups = []

		self.handler = HiveTaskConversation()
		self.ctx = {"chat_id": CHAT_ID, "message_id": 1, "callback_query_id": "cq1"}

		for name in frappe.get_all(
			"Telegram Conversation State",
			filters={"chat_id": str(CHAT_ID), "handler": "hive"},
			pluck="name",
		):
			frappe.delete_doc("Telegram Conversation State", name, force=True, ignore_permissions=True)

		self._patch(
			"bwh_bot.handlers.hive",
			send_message=self._record,
			edit_message_text=self._record_edit,
			answer_callback_query=self._record_answer,
		)
		self._patch(
			"bwh_bot.conversation",
			send_message=self._record,
			edit_message_text=self._record_edit,
			answer_callback_query=self._record_answer,
			set_message_reaction=lambda *a, **k: None,
		)
		self._patch(
			"bwh_bot.hive_client",
			active_sites=lambda: [s for s in self.sites if s.is_active],
			list_projects=lambda site: PROJECTS,
			list_members=lambda site: MEMBERS,
			create_task=self._fake_create,
			assign_task=self._fake_assign,
		)

	def _patch(self, target, **attrs):
		patcher = patch.multiple(target, **attrs)
		patcher.start()
		self.addCleanup(patcher.stop)

	# --- capture ---

	def _record(self, chat_id, text, **kwargs):
		self.sent.append(text)
		self.markups.append(kwargs.get("reply_markup"))

	def _record_edit(self, chat_id, message_id, text, **kwargs):
		self.sent.append(text)
		self.markups.append(kwargs.get("reply_markup"))

	def _record_answer(self, callback_query_id, text=None, show_alert=False):
		self.sent.append(text or "")
		self.markups.append(None)

	def _fake_create(self, site, **kwargs):
		self.created.append((site, kwargs))
		return "TASK-00007"

	def _fake_assign(self, site, task_name, users):
		self.assigned.append((task_name, users))

	@property
	def last(self):
		return self.sent[-1]

	@property
	def last_buttons(self):
		markup = self.markups[-1]
		if not markup:
			return []
		return [button.text for row in markup.inline_keyboard for button in row]

	# --- driver ---

	def _start(self):
		self.handler.handle_command(_command_message())
		return self.handler.get_active_state(CHAT_ID, TG_USER_ID)

	def _run_to_review(self, description="A description", assignees=("ada@example.com",)):
		state = self._start()
		self.handler.handle_text_input(state, CHAT_ID, "Ship the thing")
		if description is None:
			self.handler.on_action("skip_desc", None, state, self.ctx)
		else:
			self.handler.handle_text_input(state, CHAT_ID, description)
		self.handler.on_action("from", "2026-08-03", state, self.ctx)
		self.handler.on_action("to", "2026-08-07", state, self.ctx)
		self.handler.on_action("project", "PROJ-00001", state, self.ctx)
		for user in assignees:
			self.handler.on_action("assignee", user, state, self.ctx)
		self.handler.on_action("assignees_done", None, state, self.ctx)
		return state


class TestHiveConversation(HiveConversationTestCase):
	def test_creates_remote_task_with_all_fields(self):
		state = self._run_to_review()
		self.handler.on_action("confirm", None, state, self.ctx)

		self.assertEqual(len(self.created), 1)
		site, payload = self.created[0]
		self.assertEqual(site.site_url, "https://hive.example.com")
		self.assertEqual(payload["title"], "Ship the thing")
		self.assertEqual(payload["description"], "A description")
		self.assertEqual(payload["project"], "PROJ-00001")
		self.assertEqual(payload["status"], DEFAULT_STATUS)
		self.assertEqual(payload["start_date"], "2026-08-03")
		self.assertEqual(payload["due_date"], "2026-08-07")
		self.assertIn("Hive Task Created", self.last)
		self.assertIn("TASK-00007", self.last)

	def test_assignees_sent_to_remote_site(self):
		state = self._run_to_review(assignees=("ada@example.com", "grace@example.com"))
		self.handler.on_action("confirm", None, state, self.ctx)

		self.assertEqual(self.assigned, [("TASK-00007", ["ada@example.com", "grace@example.com"])])

	def test_description_can_be_skipped(self):
		state = self._run_to_review(description=None)
		self.handler.on_action("confirm", None, state, self.ctx)

		_, payload = self.created[0]
		self.assertIsNone(payload["description"])

	def test_no_assignees_means_no_assign_call(self):
		state = self._run_to_review(assignees=())
		self.handler.on_action("confirm", None, state, self.ctx)

		self.assertEqual(self.assigned, [])
		self.assertEqual(len(self.created), 1)

	def test_assignee_selection_toggles_off(self):
		state = self._start()
		self.handler.handle_text_input(state, CHAT_ID, "Toggle test")
		self.handler.on_action("skip_desc", None, state, self.ctx)
		self.handler.on_action("from", "2026-08-03", state, self.ctx)
		self.handler.on_action("to", "2026-08-07", state, self.ctx)
		self.handler.on_action("project", "PROJ-00001", state, self.ctx)

		self.handler.on_action("assignee", "ada@example.com", state, self.ctx)
		self.assertEqual(self.handler.get_data(state)["assignees"], ["ada@example.com"])
		self.assertIn("✅ Ada", self.last_buttons)
		self.assertIn("Done (1 selected)", self.last_buttons)

		self.handler.on_action("assignee", "ada@example.com", state, self.ctx)
		self.assertEqual(self.handler.get_data(state)["assignees"], [])
		self.assertNotIn("✅ Ada", self.last_buttons)

	def test_project_titles_are_offered_as_buttons(self):
		state = self._start()
		self.handler.handle_text_input(state, CHAT_ID, "Project test")
		self.handler.on_action("skip_desc", None, state, self.ctx)
		self.handler.on_action("from", "2026-08-03", state, self.ctx)
		self.handler.on_action("to", "2026-08-07", state, self.ctx)

		self.assertIn("Apollo", self.last_buttons)
		self.assertIn("Borealis", self.last_buttons)

	def test_chosen_project_shows_its_title_not_its_id(self):
		self._run_to_review()
		self.assertIn("Apollo", self.last)
		self.assertNotIn("PROJ-00001", self.last)

	def test_end_date_before_start_is_rejected(self):
		state = self._start()
		self.handler.handle_text_input(state, CHAT_ID, "Bad dates")
		self.handler.on_action("skip_desc", None, state, self.ctx)
		self.handler.on_action("from", "2026-08-10", state, self.ctx)

		self.handler.on_action("to", "2026-08-01", state, self.ctx)

		self.assertIn("can't be before the start date", self.last)
		self.assertEqual(state.step, "select_end_date")

	def test_empty_title_is_rejected(self):
		state = self._start()
		self.handler.handle_text_input(state, CHAT_ID, "   ")

		self.assertIn("can't be empty", self.last)
		self.assertEqual(state.step, "awaiting_title")

	def test_back_from_project_returns_to_end_date(self):
		state = self._start()
		self.handler.handle_text_input(state, CHAT_ID, "Back test")
		self.handler.on_action("skip_desc", None, state, self.ctx)
		self.handler.on_action("from", "2026-08-03", state, self.ctx)
		self.handler.on_action("to", "2026-08-07", state, self.ctx)
		self.assertEqual(state.step, "select_project")

		self.handler.on_back(state, self.ctx)

		self.assertEqual(state.step, "select_end_date")
		self.assertIn("end date", self.last)

	def test_remote_failure_is_reported_and_does_not_raise(self):
		state = self._run_to_review()
		with patch.object(hive_client, "create_task", side_effect=HiveSiteError("host unreachable")):
			self.handler.on_action("confirm", None, state, self.ctx)

		self.assertIn("Failed to create task", self.last)
		self.assertEqual(self.created, [])

	def test_assign_failure_still_reports_the_task_as_created(self):
		state = self._run_to_review()
		with patch.object(hive_client, "assign_task", side_effect=HiveSiteError("no permission")):
			self.handler.on_action("confirm", None, state, self.ctx)

		self.assertIn("Hive Task Created", self.last)
		self.assertIn("assigning failed", self.last)


class TestHiveEmptyAndFailingRemote(HiveConversationTestCase):
	"""What the user sees when the remote site answers but has nothing usable,
	or stops answering part way through the conversation."""

	def _to_project_step(self):
		state = self._start()
		self.handler.handle_text_input(state, CHAT_ID, "Remote edge cases")
		self.handler.on_action("skip_desc", None, state, self.ctx)
		self.handler.on_action("from", "2026-08-03", state, self.ctx)
		return state

	def test_no_projects_on_remote_aborts_with_an_explanation(self):
		state = self._to_project_step()
		with patch.object(hive_client, "list_projects", lambda site: []):
			self.handler.on_action("to", "2026-08-07", state, self.ctx)

		self.assertIn("No open projects", self.last)
		self.assertEqual(state.is_active, 0)

	def test_no_members_on_remote_aborts_with_an_explanation(self):
		state = self._to_project_step()
		self.handler.on_action("to", "2026-08-07", state, self.ctx)
		with patch.object(hive_client, "list_members", lambda site: []):
			self.handler.on_action("project", "PROJ-00001", state, self.ctx)

		self.assertIn("No active Hive members", self.last)
		self.assertEqual(state.is_active, 0)

	def test_unreachable_remote_while_listing_projects_aborts(self):
		state = self._to_project_step()

		def boom(site):
			raise HiveSiteError("Could not reach Hive: timed out")

		with patch.object(hive_client, "list_projects", boom):
			self.handler.on_action("to", "2026-08-07", state, self.ctx)

		self.assertIn("Could not reach", self.last)
		self.assertEqual(state.is_active, 0)

	def test_unreachable_remote_while_listing_members_aborts(self):
		state = self._to_project_step()
		self.handler.on_action("to", "2026-08-07", state, self.ctx)

		def boom(site):
			raise HiveSiteError("Could not reach Hive: timed out")

		with patch.object(hive_client, "list_members", boom):
			self.handler.on_action("project", "PROJ-00001", state, self.ctx)

		self.assertIn("Could not reach", self.last)
		self.assertEqual(state.is_active, 0)


class TestHiveBackNavigation(HiveConversationTestCase):
	"""Every step reachable by Go Back, walked in reverse."""

	def test_back_walks_from_review_to_description(self):
		state = self._run_to_review()
		self.assertEqual(state.step, "confirm")

		self.handler.on_back(state, self.ctx)
		self.assertEqual(state.step, "select_assignees")

		self.handler.on_back(state, self.ctx)
		self.assertEqual(state.step, "select_project")

		self.handler.on_back(state, self.ctx)
		self.assertEqual(state.step, "select_end_date")

		self.handler.on_back(state, self.ctx)
		self.assertEqual(state.step, "select_start_date")

		self.handler.on_back(state, self.ctx)
		self.assertEqual(state.step, "awaiting_description")
		self.assertIn("description", self.last)

	def test_going_back_and_forward_keeps_the_earlier_answers(self):
		state = self._run_to_review()
		self.handler.on_back(state, self.ctx)
		self.handler.on_back(state, self.ctx)

		# Re-pick the project and finish again; the title must survive.
		self.handler.on_action("project", "PROJ-00002", state, self.ctx)
		self.handler.on_action("assignees_done", None, state, self.ctx)
		self.handler.on_action("confirm", None, state, self.ctx)

		_, payload = self.created[0]
		self.assertEqual(payload["title"], "Ship the thing")
		self.assertEqual(payload["project"], "PROJ-00002")


class TestHiveCancel(HiveConversationTestCase):
	def test_cancel_clears_the_session(self):
		state = self._start()

		log = type(
			"Log",
			(),
			{
				"chat_id": CHAT_ID,
				"telegram_user_id": TG_USER_ID,
				"callback_query_id": "cq1",
				"callback_data": "hive:cancel",
			},
		)()
		self.handler.handle_callback({"message": {"message_id": 1}}, log)

		state.reload()
		self.assertEqual(state.is_active, 0)
		self.assertIn("cancelled", self.sent[-2].lower())

	def test_button_press_without_a_session_is_reported(self):
		log = type(
			"Log",
			(),
			{
				"chat_id": CHAT_ID,
				"telegram_user_id": TG_USER_ID,
				"callback_query_id": "cq1",
				"callback_data": "hive:confirm",
			},
		)()
		self.handler.handle_callback({"message": {"message_id": 1}}, log)

		self.assertIn("No active session", self.last)


class TestHiveCustomDates(HiveConversationTestCase):
	"""The "Custom date..." buttons route through the base class, which parses the
	reply and hands a date string to on_text_input rather than on_action."""

	def _to_custom_start(self):
		state = self._start()
		self.handler.handle_text_input(state, CHAT_ID, "Custom date test")
		self.handler.on_action("skip_desc", None, state, self.ctx)
		self.handler.update_state(state, "awaiting_from_date")
		return state

	def test_custom_start_date_advances_to_end_date(self):
		state = self._to_custom_start()

		self.handler.handle_text_input(state, CHAT_ID, "3 Aug 2026")

		self.assertEqual(state.step, "select_end_date")
		self.assertEqual(self.handler.get_data(state)["start_date"], "2026-08-03")
		self.assertIn("end date", self.last)

	def test_custom_end_date_advances_to_project(self):
		state = self._to_custom_start()
		self.handler.handle_text_input(state, CHAT_ID, "3 Aug 2026")
		self.handler.update_state(state, "awaiting_to_date")

		self.handler.handle_text_input(state, CHAT_ID, "7 Aug 2026")

		self.assertEqual(state.step, "select_project")
		self.assertEqual(self.handler.get_data(state)["due_date"], "2026-08-07")

	def test_custom_end_date_before_start_is_rejected(self):
		state = self._to_custom_start()
		self.handler.handle_text_input(state, CHAT_ID, "10 Aug 2026")
		self.handler.update_state(state, "awaiting_to_date")

		self.handler.handle_text_input(state, CHAT_ID, "1 Aug 2026")

		self.assertIn("can't be before the start date", self.last)
		self.assertEqual(state.step, "awaiting_to_date")

	def test_unparseable_date_is_reported(self):
		state = self._to_custom_start()

		self.handler.handle_text_input(state, CHAT_ID, "not a date")

		self.assertIn("Could not parse", self.last)
		self.assertEqual(state.step, "awaiting_from_date")

	def test_unknown_action_is_reported(self):
		state = self._start()
		self.handler.on_action("no_such_action", None, state, self.ctx)
		self.assertEqual(self.last, "Unknown action.")


class TestHiveSiteSelection(HiveConversationTestCase):
	def test_single_site_skips_the_picker(self):
		state = self._start()
		self.assertEqual(state.step, "awaiting_title")
		self.assertIn("task title", self.last)

	def test_no_configured_sites_explains_itself(self):
		self.sites = []
		with patch.object(hive_client, "active_sites", lambda: []):
			self.handler.handle_command(_command_message())
		self.assertIn("No Hive sites are configured", self.last)

	def test_inactive_sites_are_ignored(self):
		self.sites = [FakeSite(is_active=0)]
		self.handler.handle_command(_command_message())
		self.assertIn("No Hive sites are configured", self.last)

	def test_multiple_sites_prompt_for_choice(self):
		self.sites = [FakeSite("row1", "Hive A"), FakeSite("row2", "Hive B", "https://b.example.com")]
		state = self._start()

		self.assertEqual(state.step, "select_site")
		self.assertIn("Hive A", self.last_buttons)
		self.assertIn("Hive B", self.last_buttons)

		self.handler.on_action("site", "row2", state, self.ctx)
		self.assertEqual(state.step, "awaiting_title")
		self.assertEqual(self.handler.get_data(state)["site"], "row2")

	def test_site_removed_mid_conversation_is_handled(self):
		state = self._run_to_review()
		self.sites = []
		self.handler.on_action("confirm", None, state, self.ctx)

		self.assertIn("no longer configured", self.last)
		self.assertEqual(self.created, [])


class TestConversationRequirements(IntegrationTestCase):
	def test_hive_does_not_require_employee(self):
		self.assertFalse(HiveTaskConversation.requires_employee)

	def test_hr_flows_still_require_employee(self):
		from bwh_bot.handlers.leave import LeaveConversation
		from bwh_bot.handlers.wfh import WFHConversation

		self.assertTrue(LeaveConversation.requires_employee)
		self.assertTrue(WFHConversation.requires_employee)

	def test_each_command_keeps_its_own_description(self):
		"""Every conversation registers the same bound handle_command, so storing
		descriptions on the function object made the last registration win."""
		import bwh_bot.api.telegram as telegram_api

		descriptions = telegram_api.COMMAND_DESCRIPTIONS
		self.assertEqual(descriptions.get("/hive"), "Create a task in Hive")
		self.assertEqual(descriptions.get("/leave_application"), "Apply for leave")
		self.assertEqual(descriptions.get("/wfh"), "Apply for Work From Home")
		self.assertEqual(len(set(descriptions.values())), len(descriptions))


class TestHiveClient(IntegrationTestCase):
	"""The REST plumbing: auth header, query shape, error surfacing."""

	def test_auth_header_uses_token_scheme(self):
		site = FakeSite()
		with patch("bwh_bot.hive_client.get_decrypted_password", return_value="s3cret"):
			self.assertEqual(hive_client._auth_header(site), "token key:s3cret")

	def test_missing_secret_is_a_clear_error(self):
		site = FakeSite()
		with patch("bwh_bot.hive_client.get_decrypted_password", return_value=None):
			with self.assertRaises(HiveSiteError) as cm:
				hive_client._auth_header(site)
		self.assertIn("no API secret", str(cm.exception))

	def test_trailing_slash_in_site_url_does_not_double_up(self):
		site = FakeSite(url="https://hive.example.com/")
		self.assertEqual(
			hive_client.task_url(site, "TASK-1"), "https://hive.example.com/app/hive-task/TASK-1"
		)

	def test_label_falls_back_to_host(self):
		self.assertEqual(hive_client.site_label(FakeSite(label=None)), "hive.example.com")

	def test_http_error_is_wrapped_with_the_site_label(self):
		site = FakeSite()

		class Response:
			status_code = 403
			text = "forbidden"

			def json(self):
				return {"exception": "frappe.PermissionError: not allowed"}

		with patch("bwh_bot.hive_client.get_decrypted_password", return_value="s"):
			with patch("bwh_bot.hive_client.requests.request", return_value=Response()):
				with self.assertRaises(HiveSiteError) as cm:
					hive_client._request(site, "GET", "/api/resource/Hive Project")

		message = str(cm.exception)
		self.assertIn("Hive", message)
		self.assertIn("403", message)
		self.assertIn("PermissionError", message)

	def test_unreachable_host_is_wrapped(self):
		import requests

		site = FakeSite()
		with patch("bwh_bot.hive_client.get_decrypted_password", return_value="s"):
			with patch(
				"bwh_bot.hive_client.requests.request",
				side_effect=requests.ConnectionError("dns failure"),
			):
				with self.assertRaises(HiveSiteError) as cm:
					hive_client._request(site, "GET", "/api/resource/Hive Project")

		self.assertIn("Could not reach", str(cm.exception))

	def test_create_task_returns_the_remote_name(self):
		site = FakeSite()
		with patch.object(hive_client, "_request", return_value={"data": {"name": "TASK-42"}}):
			name = hive_client.create_task(
				site,
				title="T",
				project="P",
				status=DEFAULT_STATUS,
				start_date="2026-08-01",
				due_date="2026-08-02",
			)
		self.assertEqual(name, "TASK-42")

	def test_create_task_without_a_name_is_an_error(self):
		site = FakeSite()
		with patch.object(hive_client, "_request", return_value={"data": {}}):
			with self.assertRaises(HiveSiteError):
				hive_client.create_task(
					site,
					title="T",
					project="P",
					status=DEFAULT_STATUS,
					start_date="2026-08-01",
					due_date="2026-08-02",
				)

	def test_list_projects_filters_to_open_and_unarchived(self):
		site = FakeSite()
		captured = {}

		def fake_request(site, method, path, **kwargs):
			captured.update(path=path, params=kwargs.get("params"))
			return {"data": PROJECTS}

		with patch.object(hive_client, "_request", fake_request):
			result = hive_client.list_projects(site)

		self.assertEqual(result, PROJECTS)
		self.assertEqual(captured["path"], "/api/resource/Hive Project")
		self.assertIn("is_archived", captured["params"]["filters"])
		self.assertIn("Open", captured["params"]["filters"])
		self.assertEqual(captured["params"]["limit_page_length"], hive_client.MAX_PROJECTS)

	def test_list_members_filters_to_active_team_members(self):
		site = FakeSite()
		captured = {}

		def fake_request(site, method, path, **kwargs):
			captured.update(path=path, params=kwargs.get("params"))
			return {"data": MEMBERS}

		with patch.object(hive_client, "_request", fake_request):
			result = hive_client.list_members(site)

		self.assertEqual(result, MEMBERS)
		self.assertEqual(captured["path"], "/api/resource/Hive Member")
		self.assertIn("is_active", captured["params"]["filters"])
		self.assertIn("Team", captured["params"]["filters"])
		self.assertEqual(captured["params"]["limit_page_length"], hive_client.MAX_MEMBERS)

	def test_active_sites_skips_disabled_rows(self):
		settings = type("S", (), {"hive_sites": [FakeSite("a"), FakeSite("b", is_active=0)]})()
		with patch("bwh_bot.hive_client.frappe.get_single", return_value=settings):
			self.assertEqual([s.name for s in hive_client.active_sites()], ["a"])

	def test_non_json_response_is_reported(self):
		site = FakeSite()

		class Response:
			status_code = 200
			text = "<html>nope</html>"

			def json(self):
				raise ValueError("not json")

		with patch("bwh_bot.hive_client.get_decrypted_password", return_value="s"):
			with patch("bwh_bot.hive_client.requests.request", return_value=Response()):
				with self.assertRaises(HiveSiteError) as cm:
					hive_client._request(site, "GET", "/api/resource/Hive Project")

		self.assertIn("non-JSON", str(cm.exception))

	def test_error_text_falls_back_to_exc_type(self):
		class Response:
			status_code = 500
			text = ""

			def json(self):
				return {"exc_type": "ValidationError", "exc": "long traceback here"}

		message = hive_client._error_text(Response())
		self.assertEqual(message, "ValidationError")
		self.assertNotIn("traceback", message)

	def test_assign_uses_the_standard_assignment_endpoint(self):
		site = FakeSite()
		captured = {}

		def fake_request(site, method, path, **kwargs):
			captured.update(path=path, json=kwargs.get("json"))
			return {"message": "ok"}

		with patch.object(hive_client, "_request", fake_request):
			hive_client.assign_task(site, "TASK-1", ["ada@example.com"])

		self.assertEqual(captured["path"], "/api/method/frappe.desk.form.assign_to.add")
		self.assertEqual(captured["json"]["doctype"], "Hive Task")
		self.assertEqual(captured["json"]["assign_to"], ["ada@example.com"])


class TestInstallCustomFields(IntegrationTestCase):
	"""The custom fields target Frappe HR doctypes, which are optional. Without
	this guard `install-app` fails outright on a site (and in CI) without HR."""

	def test_absent_doctypes_are_skipped(self):
		from bwh_bot import install

		with patch("bwh_bot.install.frappe.db.exists", return_value=None):
			with patch("bwh_bot.install.create_custom_fields") as create:
				install._make_custom_fields()

		create.assert_not_called()

	def test_present_doctypes_are_created(self):
		from bwh_bot import install

		with patch("bwh_bot.install.frappe.db.exists", return_value="Attendance Request"):
			with patch("bwh_bot.install.create_custom_fields") as create:
				install._make_custom_fields()

		create.assert_called_once()
		fields = create.call_args[0][0]
		self.assertIn("Attendance Request", fields)

	def test_after_install_does_not_raise_without_hr(self):
		from bwh_bot import install

		with patch("bwh_bot.install.frappe.db.exists", return_value=None):
			install.after_install()
			install.after_migrate()
