import frappe
from bwh_bot.telegram_utils import get_mapped_user, is_whitelisted, send_message

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

		chat_id = message.get("chat", {}).get("id")
		chat_title = message.get("chat", {}).get("title", "")
		print(f"[BWH Bot] chat_id={chat_id} title={chat_title}")
		if not chat_id or not is_whitelisted(chat_id):
			print(f"[BWH Bot] chat {chat_id} is not whitelisted, ignoring")
			return

		text = (message.get("text") or "").strip()
		if not text.startswith("/"):
			return

		# resolve Telegram user → Frappe user
		telegram_user = message.get("from", {})
		telegram_id = telegram_user.get("id")
		print(f"[BWH Bot] from: id={telegram_id} username={telegram_user.get('username')} name={telegram_user.get('first_name')}")
		username = telegram_user.get("username")
		frappe_user = get_mapped_user(telegram_id, username)
		print(f"[BWH Bot] mapped frappe_user={frappe_user}")
		if not frappe_user:
			send_message(
				chat_id,
				"You are not registered with the bot. Please contact your administrator to get access.",
			)
			return

		frappe.set_user(frappe_user)

		command = text.split()[0].split("@")[0].lower()  # strip @botname
		handler = COMMAND_HANDLERS.get(command)
		if handler:
			handler(message)
	except Exception:
		frappe.log_error("BWH Bot Webhook Error")
	finally:
		frappe.set_user("Guest")
