import json

import frappe
from frappe.model.document import Document

from bwh_bot.telegram_utils import (
	answer_callback_query,
	get_mapped_user,
	is_whitelisted,
	send_message,
)


class TelegramWebhookLog(Document):
	def after_insert(self):
		if not self.chat_id or not is_whitelisted(self.chat_id):
			if self.command:
				send_message(self.chat_id, "Unauthorized. This bot only works in registered groups.")
			return

		if self.update_type == "callback_query":
			self.handle_callback_query()
			return

		# Check if user has an active conversation awaiting text input
		if not self.command and self.message_text:
			self.handle_text_input()
			return

		if not self.command:
			return

		frappe_user = get_mapped_user(self.telegram_user_id, self.telegram_username)
		if not frappe_user:
			send_message(
				self.chat_id,
				"You are not registered with the bot. Please contact your administrator to get access.",
			)
			return

		frappe.set_user(frappe_user)

		from bwh_bot.api.telegram import COMMAND_HANDLERS

		handler = COMMAND_HANDLERS.get(self.command)
		if handler:
			payload = json.loads(self.payload)
			message = payload.get("message") or payload.get("edited_message")
			handler(message)

	def handle_text_input(self):
		"""Handle plain text messages for active conversations awaiting input."""
		results = frappe.get_all(
			"Telegram Conversation State",
			filters={
				"chat_id": str(self.chat_id),
				"telegram_user_id": str(self.telegram_user_id),
				"is_active": 1,
				"step": ["in", ["awaiting_from_date", "awaiting_to_date"]],
			},
			pluck="name",
			limit=1,
		)
		if not results:
			return
		state_name = results[0]

		frappe_user = get_mapped_user(self.telegram_user_id, self.telegram_username)
		if not frappe_user:
			return

		frappe.set_user(frappe_user)

		state = frappe.get_doc("Telegram Conversation State", state_name)

		from bwh_bot.conversation import CONVERSATION_HANDLERS

		handler = CONVERSATION_HANDLERS.get(state.handler)
		if handler:
			handler.handle_text_input(state, self.chat_id, self.message_text)

	def handle_callback_query(self):
		frappe_user = get_mapped_user(self.telegram_user_id, self.telegram_username)
		if not frappe_user:
			answer_callback_query(self.callback_query_id, "You are not registered.", show_alert=True)
			return

		frappe.set_user(frappe_user)

		from bwh_bot.api.telegram import CALLBACK_HANDLERS

		if not self.callback_data:
			return

		prefix = self.callback_data.split(":")[0]
		handler = CALLBACK_HANDLERS.get(prefix)
		if handler:
			payload = json.loads(self.payload)
			handler(payload.get("callback_query", {}), self)
