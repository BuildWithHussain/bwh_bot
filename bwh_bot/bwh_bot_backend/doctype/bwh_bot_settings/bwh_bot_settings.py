import frappe
from frappe.model.document import Document


class BWHBotSettings(Document):
	@frappe.whitelist()
	def register_webhook(self):
		from bwh_bot.telegram_utils import register_bot_commands, register_webhook

		url = register_webhook(self.webhook_url or None)

		# Register bot commands with Telegram
		from bwh_bot.api.telegram import COMMAND_HANDLERS

		commands = []
		for cmd, fn in COMMAND_HANDLERS.items():
			desc = getattr(fn, "_description", f"Run {cmd}")
			commands.append((cmd.lstrip("/"), desc))

		if commands:
			register_bot_commands(commands)

		frappe.msgprint(f"Webhook registered at {url}")
