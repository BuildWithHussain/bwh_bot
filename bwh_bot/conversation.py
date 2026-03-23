import json

import frappe

from bwh_bot.telegram_utils import (
	answer_callback_query,
	edit_message_text,
	get_employee_from_user,
	send_message,
	set_message_reaction,
)

CONVERSATION_HANDLERS = {}


class BotConversation:
	handler_name = ""
	callback_prefix = ""
	command = ""
	command_description = ""
	title = ""

	def __init_subclass__(cls, **kwargs):
		super().__init_subclass__(**kwargs)
		if cls.handler_name:
			CONVERSATION_HANDLERS[cls.handler_name] = cls()

	# --- State management ---

	def get_or_create_state(self, chat_id, telegram_user_id, initial_step="start"):
		existing = frappe.db.get_value(
			"Telegram Conversation State",
			{
				"chat_id": str(chat_id),
				"telegram_user_id": str(telegram_user_id),
				"handler": self.handler_name,
				"is_active": 1,
			},
			"name",
		)
		if existing:
			return frappe.get_doc("Telegram Conversation State", existing)

		state = frappe.get_doc({
			"doctype": "Telegram Conversation State",
			"chat_id": str(chat_id),
			"telegram_user_id": str(telegram_user_id),
			"handler": self.handler_name,
			"step": initial_step,
			"is_active": 1,
			"data": json.dumps({}),
			"expires_at": frappe.utils.add_to_date(None, hours=1),
		})
		state.insert(ignore_permissions=True)
		return state

	def get_active_state(self, chat_id, telegram_user_id):
		name = frappe.db.get_value(
			"Telegram Conversation State",
			{
				"chat_id": str(chat_id),
				"telegram_user_id": str(telegram_user_id),
				"handler": self.handler_name,
				"is_active": 1,
			},
			"name",
		)
		if name:
			return frappe.get_doc("Telegram Conversation State", name)
		return None

	@staticmethod
	def clear_state(state):
		state.is_active = 0
		state.save(ignore_permissions=True)

	@staticmethod
	def update_state(state, step, data_update=None):
		state.step = step
		if data_update:
			current = json.loads(state.data or "{}")
			current.update(data_update)
			state.data = json.dumps(current)
		state.save(ignore_permissions=True)

	@staticmethod
	def get_data(state):
		return json.loads(state.data or "{}")

	# --- Command entry point ---

	def handle_command(self, message):
		chat_id = message["chat"]["id"]
		message_id = message["message_id"]
		message_thread_id = message.get("message_thread_id")

		try:
			set_message_reaction(chat_id, message_id, "👍")
		except Exception:
			pass

		employee = get_employee_from_user(frappe.session.user)
		if not employee:
			send_message(chat_id, "You are not linked to any active employee record.", reply_to_message_id=message_id, message_thread_id=message_thread_id)
			return

		state = self.get_or_create_state(chat_id, message["from"]["id"])
		self.update_state(state, "start", {"employee": employee, "message_thread_id": message_thread_id})
		self.on_start(message, state, employee)

	# --- Callback entry point ---

	def handle_callback(self, callback_query, log):
		chat_id = log.chat_id
		telegram_user_id = log.telegram_user_id
		callback_query_id = log.callback_query_id
		callback_data = log.callback_data
		message_id = callback_query.get("message", {}).get("message_id")

		parts = callback_data.split(":", 2)
		if len(parts) < 2:
			answer_callback_query(callback_query_id, "Invalid action.")
			return

		action = parts[1]
		value = parts[2] if len(parts) > 2 else None

		state = self.get_active_state(chat_id, telegram_user_id)
		if not state:
			answer_callback_query(
				callback_query_id,
				f"No active session. Use {self.command} to start.",
				show_alert=True,
			)
			return

		ctx = {"chat_id": chat_id, "message_id": message_id, "callback_query_id": callback_query_id}

		if action == "cancel":
			self.clear_state(state)
			edit_message_text(chat_id, message_id, f"{self.title} cancelled.")
			answer_callback_query(callback_query_id, "Cancelled")
			return

		if action == "back":
			answer_callback_query(callback_query_id)
			self.on_back(state, ctx)
			return

		if action == "custom_from":
			self.update_state(state, "awaiting_from_date")
			answer_callback_query(callback_query_id)
			data = self.get_data(state)
			header = self._build_header(data)
			edit_message_text(
				chat_id, message_id,
				f"{header}\n\nReply to this message with the <b>from date</b> (e.g. 25 Mar 2026):",
				parse_mode="HTML",
			)
			return

		if action == "custom_to":
			self.update_state(state, "awaiting_to_date")
			answer_callback_query(callback_query_id)
			data = self.get_data(state)
			header = self._build_header(data)
			edit_message_text(
				chat_id, message_id,
				f"{header}\n\nReply to this message with the <b>to date</b> (e.g. 28 Mar 2026):",
				parse_mode="HTML",
			)
			return

		self.on_action(action, value, state, ctx)

	# --- Text input entry point ---

	def handle_text_input(self, state, chat_id, text):
		text = text.strip()
		data = self.get_data(state)
		message_thread_id = data.get("message_thread_id")

		try:
			parsed = frappe.utils.getdate(text, parse_day_first=True)
			if not parsed:
				raise ValueError("Could not parse date")
			date_str = str(parsed)
		except Exception:
			send_message(
				chat_id,
				"Could not parse that date. Try formats like <code>25 Mar 2026</code>, <code>25-03-2026</code>, or <code>2026-03-25</code>.",
				parse_mode="HTML",
				message_thread_id=message_thread_id,
			)
			return

		self.on_text_input(state, chat_id, date_str)

	# --- Hooks for subclasses ---

	def on_start(self, message, state, employee):
		raise NotImplementedError

	def on_action(self, action, value, state, ctx):
		answer_callback_query(ctx["callback_query_id"], "Unknown action.")

	def on_back(self, state, ctx):
		pass

	def on_text_input(self, state, chat_id, date_str):
		pass

	# --- Helpers ---

	def _build_header(self, data):
		"""Build a header string from accumulated state data. Override for custom headers."""
		return f"<b>{self.title}</b>"
