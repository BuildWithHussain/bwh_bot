import asyncio

import frappe
import telegram


def get_bot():
	from frappe.utils.password import get_decrypted_password

	token = get_decrypted_password("BWH Bot Settings", "BWH Bot Settings", "bot_token")
	return telegram.Bot(token=token)


def send_message(chat_id, text, parse_mode=None, reply_markup=None, reply_to_message_id=None, message_thread_id=None):
	bot = get_bot()
	asyncio.run(
		bot.send_message(
			chat_id=chat_id,
			text=text,
			parse_mode=parse_mode,
			reply_markup=reply_markup,
			reply_to_message_id=reply_to_message_id,
			message_thread_id=message_thread_id,
		)
	)


def edit_message_text(chat_id, message_id, text, parse_mode=None, reply_markup=None):
	bot = get_bot()
	asyncio.run(
		bot.edit_message_text(
			chat_id=chat_id,
			message_id=message_id,
			text=text,
			parse_mode=parse_mode,
			reply_markup=reply_markup,
		)
	)


def answer_callback_query(callback_query_id, text=None, show_alert=False):
	bot = get_bot()
	asyncio.run(
		bot.answer_callback_query(
			callback_query_id=callback_query_id,
			text=text,
			show_alert=show_alert,
		)
	)


def set_message_reaction(chat_id, message_id, emoji="👍"):
	bot = get_bot()
	asyncio.run(
		bot.set_message_reaction(
			chat_id=chat_id,
			message_id=message_id,
			reaction=[telegram.ReactionTypeEmoji(emoji=emoji)],
		)
	)


def broadcast_to_whitelisted_chats(text, parse_mode="HTML"):
	"""Send a message to every whitelisted chat, logging (not raising) on failure."""
	settings = frappe.get_single("BWH Bot Settings")
	for chat in settings.whitelisted_chats:
		try:
			send_message(chat.chat_id, text, parse_mode=parse_mode)
		except Exception:
			frappe.log_error(f"Failed to send Telegram notification to chat {chat.chat_id}")


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


def get_telegram_user_for_frappe_user(user):
	"""Reverse lookup: Frappe User → telegram_user_id"""
	settings = frappe.get_single("BWH Bot Settings")
	for row in settings.user_mappings:
		if row.user == user:
			return row.telegram_id or row.telegram_name
	return None


def get_employee_from_user(user):
	return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


def get_leave_types_for_employee(employee):
	today = frappe.utils.today()
	allocations = frappe.get_all(
		"Leave Allocation",
		filters={
			"employee": employee,
			"docstatus": 1,
			"from_date": ["<=", today],
			"to_date": [">=", today],
		},
		fields=["leave_type", "total_leaves_allocated", "new_leaves_allocated"],
	)

	result = []
	for alloc in allocations:
		from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

		balance = get_leave_balance_on(employee, alloc.leave_type, today)
		result.append({
			"leave_type": alloc.leave_type,
			"balance": balance,
		})
	return result


def register_webhook(url=None):
	site_url = url or frappe.utils.get_url()
	webhook_url = f"{site_url}/api/method/bwh_bot.api.telegram.hook"

	settings = frappe.get_single("BWH Bot Settings")
	secret = settings.webhook_secret or None

	bot = get_bot()

	asyncio.run(bot.set_webhook(url=webhook_url, secret_token=secret))
	return webhook_url


def register_bot_commands(commands_list):
	"""Register commands with Telegram so they show in the / menu.
	commands_list: list of (command, description) tuples
	"""
	bot = get_bot()
	bot_commands = [telegram.BotCommand(cmd, desc) for cmd, desc in commands_list]
	asyncio.run(bot.set_my_commands(bot_commands))
