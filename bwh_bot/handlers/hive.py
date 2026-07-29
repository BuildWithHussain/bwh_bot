import frappe
from telegram import InlineKeyboardButton

from bwh_bot import hive_client
from bwh_bot.conversation import BotConversation
from bwh_bot.hive_client import HiveSiteError
from bwh_bot.telegram_utils import answer_callback_query, edit_message_text, send_message
from bwh_bot.ui import (
	confirm_buttons,
	from_date_buttons,
	make_keyboard,
	nav_buttons,
	to_date_buttons,
)

# Status a Telegram-created task lands in. Every other Hive Task status is a
# valid transition target from this one.
DEFAULT_STATUS = "To Do"


class HiveTaskConversation(BotConversation):
	handler_name = "hive"
	callback_prefix = "hive"
	command = "/hive"
	command_description = "Create a task in Hive"
	title = "New Hive Task"

	# Tasks are created on a remote Hive site over its API, so this flow needs
	# neither Frappe HR nor Hive installed alongside the bot.
	requires_employee = False

	# --- Step 1: pick a site (skipped when only one is configured) ------------

	def on_start(self, message, state, employee):
		chat_id = message["chat"]["id"]
		message_thread_id = message.get("message_thread_id")
		reply_to = message["message_id"]

		sites = hive_client.active_sites()
		if not sites:
			self.clear_state(state)
			send_message(
				chat_id,
				"No Hive sites are configured. Add one under Hive Sites in BWH Bot Settings.",
				reply_to_message_id=reply_to,
				message_thread_id=message_thread_id,
			)
			return

		if len(sites) == 1:
			self.update_state(state, "awaiting_title", _site_data(sites[0]))
			send_message(
				chat_id,
				f"<b>{self.title}</b>\n\nReply with the <b>task title</b>:",
				parse_mode="HTML",
				reply_to_message_id=reply_to,
				message_thread_id=message_thread_id,
			)
			return

		self.update_state(state, "select_site")
		send_message(
			chat_id,
			f"<b>{self.title}</b>\n\nSelect the <b>Hive site</b>:",
			parse_mode="HTML",
			reply_markup=make_keyboard(
				[
					[
						InlineKeyboardButton(
							hive_client.site_label(site),
							callback_data=f"{self.callback_prefix}:site:{site.name}",
						)
					]
					for site in sites
				],
				nav_buttons(self.callback_prefix, show_back=False),
			),
			reply_to_message_id=reply_to,
			message_thread_id=message_thread_id,
		)

	# --- Free-text steps: title, description ---------------------------------

	def on_raw_text_input(self, state, chat_id, text):
		message_thread_id = self.get_data(state).get("message_thread_id")

		if state.step == "awaiting_title":
			title = text.strip()
			if not title:
				send_message(
					chat_id,
					"Task title can't be empty. Reply with the <b>task title</b>:",
					parse_mode="HTML",
					message_thread_id=message_thread_id,
				)
				return

			self.update_state(state, "awaiting_description", {"title": title})
			self._prompt_description(state, chat_id, message_thread_id=message_thread_id)

		elif state.step == "awaiting_description":
			self.update_state(state, "select_start_date", {"description": text.strip()})
			self._prompt_start_date(state, chat_id, message_thread_id=message_thread_id)

	# --- Date steps ----------------------------------------------------------
	# Quick-pick buttons emit `from`/`to` actions (see on_action). The base class
	# routes the "Custom date..." buttons through awaiting_from_date /
	# awaiting_to_date and hands the parsed date to on_text_input.

	def on_text_input(self, state, chat_id, date_str):
		message_thread_id = self.get_data(state).get("message_thread_id")

		if state.step == "awaiting_from_date":
			self.update_state(state, "select_end_date", {"start_date": date_str})
			self._prompt_end_date(state, chat_id, message_thread_id=message_thread_id)

		elif state.step == "awaiting_to_date":
			if not self._reject_end_before_start(state, chat_id, date_str, message_thread_id):
				return
			self.update_state(state, "select_project", {"due_date": date_str})
			self._prompt_project(state, chat_id, message_thread_id=message_thread_id)

	# --- Button actions ------------------------------------------------------

	def on_action(self, action, value, state, ctx):
		chat_id, message_id, cqid = ctx["chat_id"], ctx["message_id"], ctx["callback_query_id"]

		if action == "site":
			site = self._find_site(value)
			if not site:
				answer_callback_query(cqid, "That site is no longer configured.", show_alert=True)
				return
			self.update_state(state, "awaiting_title", _site_data(site))
			answer_callback_query(cqid)
			edit_message_text(
				chat_id,
				message_id,
				f"{self._build_header(self.get_data(state))}\n\nReply with the <b>task title</b>:",
				parse_mode="HTML",
			)

		elif action == "skip_desc":
			self.update_state(state, "select_start_date", {"description": ""})
			answer_callback_query(cqid)
			self._prompt_start_date(state, chat_id, message_id=message_id)

		elif action == "from":
			self.update_state(state, "select_end_date", {"start_date": value})
			answer_callback_query(cqid)
			self._prompt_end_date(state, chat_id, message_id=message_id)

		elif action == "to":
			if not self._reject_end_before_start(state, chat_id, value, None, cqid=cqid):
				return
			self.update_state(state, "select_project", {"due_date": value})
			answer_callback_query(cqid)
			self._prompt_project(state, chat_id, message_id=message_id)

		elif action == "project":
			project_title = self.get_data(state).get("project_titles", {}).get(value, value)
			self.update_state(state, "select_assignees", {"project": value, "project_title": project_title})
			answer_callback_query(cqid)
			self._prompt_assignees(state, chat_id, message_id=message_id)

		elif action == "assignee":
			self._toggle_assignee(state, value)
			answer_callback_query(cqid)
			self._prompt_assignees(state, chat_id, message_id=message_id)

		elif action == "assignees_done":
			self.update_state(state, "confirm")
			answer_callback_query(cqid)
			self._show_summary(state, chat_id, message_id)

		elif action == "confirm":
			self._create_task(state, ctx)

		else:
			answer_callback_query(cqid, "Unknown action.")

	def on_back(self, state, ctx):
		chat_id, message_id = ctx["chat_id"], ctx["message_id"]
		step = state.step

		if step == "select_start_date":
			self.update_state(state, "awaiting_description")
			self._prompt_description(state, chat_id, message_id=message_id)

		elif step == "select_end_date":
			self.update_state(state, "select_start_date")
			self._prompt_start_date(state, chat_id, message_id=message_id)

		elif step == "select_project":
			self.update_state(state, "select_end_date")
			self._prompt_end_date(state, chat_id, message_id=message_id)

		elif step == "select_assignees":
			self.update_state(state, "select_project")
			self._prompt_project(state, chat_id, message_id=message_id)

		elif step == "confirm":
			self.update_state(state, "select_assignees")
			self._prompt_assignees(state, chat_id, message_id=message_id)

	# --- Prompts -------------------------------------------------------------

	def _prompt_description(self, state, chat_id, message_id=None, message_thread_id=None):
		self._send(
			chat_id,
			f"{self._build_header(self.get_data(state))}\n\nReply with a <b>description</b>, or tap Skip:",
			make_keyboard(
				[
					[
						InlineKeyboardButton(
							"Skip (no description)",
							callback_data=f"{self.callback_prefix}:skip_desc",
						)
					]
				],
				nav_buttons(self.callback_prefix, show_back=False),
			),
			message_id=message_id,
			message_thread_id=message_thread_id,
		)

	def _prompt_start_date(self, state, chat_id, message_id=None, message_thread_id=None):
		self._send(
			chat_id,
			f"{self._build_header(self.get_data(state))}\n\nSelect <b>start date</b>:",
			make_keyboard(
				from_date_buttons(self.callback_prefix, include_today=True),
				nav_buttons(self.callback_prefix),
			),
			message_id=message_id,
			message_thread_id=message_thread_id,
		)

	def _prompt_end_date(self, state, chat_id, message_id=None, message_thread_id=None):
		data = self.get_data(state)
		self._send(
			chat_id,
			f"{self._build_header(data)}\n\nSelect <b>end date</b>:",
			make_keyboard(
				to_date_buttons(self.callback_prefix, data["start_date"]),
				nav_buttons(self.callback_prefix),
			),
			message_id=message_id,
			message_thread_id=message_thread_id,
		)

	def _prompt_project(self, state, chat_id, message_id=None, message_thread_id=None):
		site = self._current_site(state)
		if not site:
			self._abort(state, chat_id, _SITE_GONE, message_id, message_thread_id)
			return

		try:
			projects = hive_client.list_projects(site)
		except HiveSiteError as e:
			self._abort(state, chat_id, str(e), message_id, message_thread_id)
			return

		if not projects:
			self._abort(
				state,
				chat_id,
				f"No open projects found on {hive_client.site_label(site)}. Create one first.",
				message_id,
				message_thread_id,
			)
			return

		# Cache the titles so later steps can label the chosen project without
		# another round trip to the remote site.
		self.update_state(
			state,
			state.step,
			{"project_titles": {p["name"]: p.get("title") or p["name"] for p in projects}},
		)

		self._send(
			chat_id,
			f"{self._build_header(self.get_data(state))}\n\nSelect <b>project</b>:",
			make_keyboard(
				_two_per_row(
					[
						(p.get("title") or p["name"], f"{self.callback_prefix}:project:{p['name']}")
						for p in projects
					]
				),
				nav_buttons(self.callback_prefix),
			),
			message_id=message_id,
			message_thread_id=message_thread_id,
		)

	def _prompt_assignees(self, state, chat_id, message_id=None, message_thread_id=None):
		"""Multi-select picker: each tap toggles a member, Done moves on."""
		site = self._current_site(state)
		if not site:
			self._abort(state, chat_id, _SITE_GONE, message_id, message_thread_id)
			return

		try:
			members = hive_client.list_members(site)
		except HiveSiteError as e:
			self._abort(state, chat_id, str(e), message_id, message_thread_id)
			return

		if not members:
			self._abort(
				state,
				chat_id,
				f"No active Hive members found on {hive_client.site_label(site)}.",
				message_id,
				message_thread_id,
			)
			return

		selected = set(self.get_data(state).get("assignees") or [])
		rows = _two_per_row(
			[
				(
					f"{'✅ ' if m['user'] in selected else ''}{m.get('member_name') or m['user']}",
					f"{self.callback_prefix}:assignee:{m['user']}",
				)
				for m in members
			]
		)
		done_label = f"Done ({len(selected)} selected)" if selected else "Done (no assignees)"
		rows.append(
			[InlineKeyboardButton(done_label, callback_data=f"{self.callback_prefix}:assignees_done")]
		)

		self._send(
			chat_id,
			f"{self._build_header(self.get_data(state))}\n\nSelect <b>assignees</b> (tap to toggle):",
			make_keyboard(rows, nav_buttons(self.callback_prefix)),
			message_id=message_id,
			message_thread_id=message_thread_id,
		)

	def _show_summary(self, state, chat_id, message_id):
		data = self.get_data(state)
		assignees = data.get("assignees") or []
		description = data.get("description") or ""

		self._send(
			chat_id,
			(
				f"<b>{self.title} — Review</b>\n\n"
				f"<b>Site:</b> {frappe.utils.escape_html(data['site_label'])}\n"
				f"<b>Title:</b> {frappe.utils.escape_html(data['title'])}\n"
				f"<b>Description:</b> {frappe.utils.escape_html(description) if description else '—'}\n"
				f"<b>Project:</b> {frappe.utils.escape_html(data['project_title'])}\n"
				f"<b>Start:</b> {data['start_date']}\n"
				f"<b>End:</b> {data['due_date']}\n"
				f"<b>Assignees:</b> {', '.join(assignees) if assignees else '—'}\n\n"
				"Create this task?"
			),
			make_keyboard(confirm_buttons(self.callback_prefix, "Confirm & Create")),
			message_id=message_id,
		)

	# --- Creation ------------------------------------------------------------

	def _create_task(self, state, ctx):
		data = self.get_data(state)
		chat_id, message_id, cqid = ctx["chat_id"], ctx["message_id"], ctx["callback_query_id"]

		site = self._current_site(state)
		if not site:
			self._abort(state, chat_id, _SITE_GONE, message_id, None)
			answer_callback_query(cqid, "Site no longer configured.", show_alert=True)
			return

		self.clear_state(state)
		assignees = data.get("assignees") or []

		try:
			task_name = hive_client.create_task(
				site,
				title=data["title"],
				project=data["project"],
				status=DEFAULT_STATUS,
				start_date=data["start_date"],
				due_date=data["due_date"],
				description=data.get("description") or None,
			)
		except HiveSiteError as e:
			answer_callback_query(cqid, "Failed to create task.", show_alert=True)
			edit_message_text(chat_id, message_id, f"Failed to create task: {e}")
			return

		# Assignment is best-effort: the task exists on the remote site either way,
		# so report success rather than leaving the user unsure what happened.
		assign_note = ""
		if assignees:
			try:
				hive_client.assign_task(site, task_name, assignees)
			except HiveSiteError:
				frappe.log_error(
					title="hive: remote assign failed",
					message=f"Assign {assignees} to {task_name} on {site.site_url}",
				)
				assign_note = "\n⚠️ Task created, but assigning failed — assign manually in Hive."

		answer_callback_query(cqid, "Task created!")
		edit_message_text(
			chat_id,
			message_id,
			(
				f"<b>✅ Hive Task Created</b>\n\n"
				f"<b>Site:</b> {frappe.utils.escape_html(data['site_label'])}\n"
				f"<b>ID:</b> {task_name}\n"
				f"<b>Title:</b> {frappe.utils.escape_html(data['title'])}\n"
				f"<b>Project:</b> {frappe.utils.escape_html(data['project_title'])}\n"
				f"<b>Start:</b> {data['start_date']}\n"
				f"<b>End:</b> {data['due_date']}\n"
				f"<b>Status:</b> {DEFAULT_STATUS}\n"
				f"<b>Assignees:</b> {', '.join(assignees) if assignees else '—'}\n"
				f'<a href="{hive_client.task_url(site, task_name)}">Open in Hive</a>'
				f"{assign_note}"
			),
			parse_mode="HTML",
		)

	# --- Helpers -------------------------------------------------------------

	def _send(self, chat_id, text, reply_markup, message_id=None, message_thread_id=None):
		"""Edit in place when reacting to a button, otherwise post a new message."""
		if message_id:
			edit_message_text(chat_id, message_id, text, parse_mode="HTML", reply_markup=reply_markup)
		else:
			send_message(
				chat_id,
				text,
				parse_mode="HTML",
				reply_markup=reply_markup,
				message_thread_id=message_thread_id,
			)

	def _abort(self, state, chat_id, text, message_id, message_thread_id):
		self.clear_state(state)
		if message_id:
			edit_message_text(chat_id, message_id, text)
		else:
			send_message(chat_id, text, message_thread_id=message_thread_id)

	def _find_site(self, row_name):
		return next((s for s in hive_client.active_sites() if s.name == row_name), None)

	def _current_site(self, state):
		"""Re-read the site from settings each time: the conversation outlives the
		request that started it, and the row may have been edited or disabled."""
		return self._find_site(self.get_data(state).get("site"))

	def _toggle_assignee(self, state, user):
		selected = self.get_data(state).get("assignees") or []
		if user in selected:
			selected.remove(user)
		else:
			selected.append(user)
		self.update_state(state, state.step, {"assignees": selected})

	def _reject_end_before_start(self, state, chat_id, end_date, message_thread_id, cqid=None):
		"""Hive treats due_date as on or after start_date; reject anything earlier."""
		start = self.get_data(state).get("start_date")
		if start and frappe.utils.getdate(end_date) < frappe.utils.getdate(start):
			msg = f"End date ({end_date}) can't be before the start date ({start})."
			if cqid:
				answer_callback_query(cqid, msg, show_alert=True)
			else:
				send_message(chat_id, msg, message_thread_id=message_thread_id)
			return False
		return True

	def _build_header(self, data):
		parts = [f"<b>{self.title}</b>"]
		if data.get("site_label"):
			parts.append(f"<b>Site:</b> {frappe.utils.escape_html(data['site_label'])}")
		if data.get("title"):
			parts.append(f"<b>Title:</b> {frappe.utils.escape_html(data['title'])}")
		if data.get("description"):
			parts.append(f"<b>Description:</b> {frappe.utils.escape_html(data['description'])}")
		if data.get("start_date"):
			parts.append(f"<b>Start:</b> {data['start_date']}")
		if data.get("due_date"):
			parts.append(f"<b>End:</b> {data['due_date']}")
		if data.get("project_title"):
			parts.append(f"<b>Project:</b> {frappe.utils.escape_html(data['project_title'])}")
		return "\n".join(parts)


_SITE_GONE = "That Hive site is no longer configured. Start again with /hive."


def _site_data(site):
	return {"site": site.name, "site_label": hive_client.site_label(site)}


def _two_per_row(entries):
	"""Lay out (label, callback_data) pairs two to a row."""
	rows, row = [], []
	for label, callback_data in entries:
		row.append(InlineKeyboardButton(label, callback_data=callback_data))
		if len(row) == 2:
			rows.append(row)
			row = []
	if row:
		rows.append(row)
	return rows
