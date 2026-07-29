import json
from datetime import datetime

import frappe

COMMAND_HANDLERS = {}
COMMAND_DESCRIPTIONS = {}
CALLBACK_HANDLERS = {}


def register_command(command, description=None):
	def decorator(fn):
		COMMAND_HANDLERS[command] = fn
		# Keyed by command rather than stashed on the function: every conversation
		# registers the same bound BotConversation.handle_command, so an attribute
		# on the function is shared and the last registration wins for all of them.
		if description:
			COMMAND_DESCRIPTIONS[command] = description
		return fn

	return decorator


def register_callback(prefix):
	def decorator(fn):
		CALLBACK_HANDLERS[prefix] = fn
		return fn

	return decorator


# Importing the handler modules is what registers them: ping registers a plain
# command, and the conversation subclasses self-register via __init_subclass__.
from bwh_bot.conversation import CONVERSATION_HANDLERS
from bwh_bot.handlers import hive, leave, petty_cash, ping, wfh

# Register conversation handlers into COMMAND_HANDLERS and CALLBACK_HANDLERS.
for _handler in CONVERSATION_HANDLERS.values():
	if _handler.command:
		register_command(_handler.command, _handler.command_description)(_handler.handle_command)
	if _handler.callback_prefix:
		register_callback(_handler.callback_prefix)(_handler.handle_callback)


# Telegram calls this webhook unauthenticated by design, so it cannot require a
# session. The shared secret checked below (X-Telegram-Bot-Api-Secret-Token) is
# what authenticates the request, and each update is gated again by the chat
# whitelist before any handler runs.
@frappe.whitelist(allow_guest=True)  # nosemgrep
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

		# Handle callback_query updates
		callback_query = data.get("callback_query")
		if callback_query:
			_handle_callback_query(data, callback_query)
			return

		# Handle message updates
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

		doc = frappe.get_doc(
			{
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
				"message_thread_id": str(message["message_thread_id"])
				if message.get("message_thread_id")
				else None,
				"message_date": message_date,
				"payload": json.dumps(data, indent=2),
			}
		)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error("BWH Bot Webhook Error")
	finally:
		frappe.set_user("Guest")


def _handle_callback_query(data, callback_query):
	message = callback_query.get("message", {})
	chat = message.get("chat", {})
	telegram_user = callback_query.get("from", {})

	message_date = None
	if message.get("date"):
		message_date = datetime.fromtimestamp(message["date"])

	doc = frappe.get_doc(
		{
			"doctype": "Telegram Webhook Log",
			"update_type": "callback_query",
			"chat_id": str(chat.get("id", "")),
			"chat_title": chat.get("title", ""),
			"telegram_user_id": str(telegram_user.get("id", "")),
			"telegram_username": telegram_user.get("username", ""),
			"telegram_user_name": f"{telegram_user.get('first_name', '')} {telegram_user.get('last_name', '')}".strip(),
			"callback_query_id": callback_query.get("id", ""),
			"callback_data": callback_query.get("data", ""),
			"message_id": str(message.get("message_id", "")),
			"message_thread_id": str(message["message_thread_id"])
			if message.get("message_thread_id")
			else None,
			"message_date": message_date,
			"payload": json.dumps(data, indent=2),
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
