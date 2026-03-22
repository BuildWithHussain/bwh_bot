import frappe
import telegram


def get_bot():
	from frappe.utils.password import get_decrypted_password

	token = get_decrypted_password("BWH Bot Settings", "BWH Bot Settings", "bot_token")
	return telegram.Bot(token=token)


def send_message(chat_id, text):
	bot = get_bot()
	import asyncio

	asyncio.run(bot.send_message(chat_id=chat_id, text=text))


def is_whitelisted(chat_id):
	settings = frappe.get_single("BWH Bot Settings")
	chat_id = str(chat_id)
	return any(row.chat_id == chat_id for row in settings.whitelisted_chats)


def get_mapped_user(telegram_id, username=None):
	settings = frappe.get_single("BWH Bot Settings")
	telegram_id = str(telegram_id) if telegram_id else None
	for row in settings.user_mappings:
		if telegram_id and row.telegram_id == telegram_id:
			return row.user
		if username and row.telegram_name and row.telegram_name.lstrip("@").lower() == username.lower():
			return row.user
	return None


def register_webhook(url=None):
	site_url = url or frappe.utils.get_url()
	webhook_url = f"{site_url}/api/method/bwh_bot.api.telegram.hook"

	settings = frappe.get_single("BWH Bot Settings")
	secret = settings.webhook_secret or None

	bot = get_bot()
	import asyncio

	asyncio.run(bot.set_webhook(url=webhook_url, secret_token=secret))
	return webhook_url
