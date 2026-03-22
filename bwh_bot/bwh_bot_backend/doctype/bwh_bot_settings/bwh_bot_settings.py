import frappe
from frappe.model.document import Document


class BWHBotSettings(Document):
	@frappe.whitelist()
	def register_webhook(self):
		from bwh_bot.telegram_utils import register_webhook

		register_webhook()
		frappe.msgprint("Webhook registered successfully.")
