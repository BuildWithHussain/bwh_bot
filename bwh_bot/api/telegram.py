import json
from datetime import datetime

import frappe

COMMAND_HANDLERS = {}


def register_command(command):
	def decorator(fn):
		COMMAND_HANDLERS[command] = fn
		return fn

	return decorator


# import handlers to register them
from bwh_bot.handlers import ping  # noqa: F401, E402


@frappe.whitelist(allow_guest=True)
def hook(**kwargs):
	try:
		settings = frappe.get_single("BWH Bot Settings")
		secret = settings.webhook_secret
		if secret:
			token = frappe.request.headers.get("X-Telegram-Bot-Api-Secret-Token")
			if token != secret:
				return

		frappe.set_user("Administrator")
		data = frappe.request.get_json(force=True)

		message = data.get("message") or data.get("edited_message")
		if not message:
			return

		update_type = "message" if data.get("message") else "edited_message"
		chat = message.get("chat", {})
		telegram_user = message.get("from", {})
		text = (message.get("text") or "").strip()
		command = None
		if text.startswith("/"):
			command = text.split()[0].split("@")[0].lower()

		message_date = None
		if message.get("date"):
			message_date = datetime.fromtimestamp(message["date"])

		doc = frappe.get_doc({
			"doctype": "Telegram Webhook Log",
			"update_type": update_type,
			"chat_id": str(chat.get("id", "")),
			"chat_title": chat.get("title", ""),
			"telegram_user_id": str(telegram_user.get("id", "")),
			"telegram_username": telegram_user.get("username", ""),
			"telegram_user_name": f"{telegram_user.get('first_name', '')} {telegram_user.get('last_name', '')}".strip(),
			"command": command,
			"message_text": text,
			"message_id": str(message.get("message_id", "")),
			"message_date": message_date,
			"payload": json.dumps(data, indent=2),
		})
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error("BWH Bot Webhook Error")
	finally:
		frappe.set_user("Guest")
