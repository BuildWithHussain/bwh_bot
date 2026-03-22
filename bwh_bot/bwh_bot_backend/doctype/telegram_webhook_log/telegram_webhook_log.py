import json

import frappe
from frappe.model.document import Document

from bwh_bot.telegram_utils import get_mapped_user, is_whitelisted, send_message


class TelegramWebhookLog(Document):
	def after_insert(self):
		if not self.chat_id or not is_whitelisted(self.chat_id):
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
			message = json.loads(self.payload).get("message") or json.loads(self.payload).get("edited_message")
			handler(message)
