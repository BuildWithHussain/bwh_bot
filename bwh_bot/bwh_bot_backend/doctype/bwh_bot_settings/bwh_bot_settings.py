import frappe
from frappe.model.document import Document


class BWHBotSettings(Document):
	@frappe.whitelist()
	def register_webhook(self):
		from bwh_bot.telegram_utils import register_bot_commands, register_webhook

		url = register_webhook(self.webhook_url or None)

		# Register bot commands with Telegram
		from bwh_bot.api.telegram import COMMAND_DESCRIPTIONS, COMMAND_HANDLERS

		commands = []
		for cmd in COMMAND_HANDLERS:
			desc = COMMAND_DESCRIPTIONS.get(cmd, f"Run {cmd}")
			commands.append((cmd.lstrip("/"), desc))

		if commands:
			register_bot_commands(commands)

		frappe.msgprint(f"Webhook registered at {url}")
