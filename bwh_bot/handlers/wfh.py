import json

import frappe
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bwh_bot.api.telegram import register_callback, register_command
from bwh_bot.telegram_utils import (
	answer_callback_query,
	edit_message_text,
	get_employee_from_user,
	send_message,
	set_message_reaction,
)

CALLBACK_PREFIX = "wfh"


def _get_or_create_state(chat_id, telegram_user_id):
	existing = frappe.db.get_value(
		"Telegram Conversation State",
		{"chat_id": str(chat_id), "telegram_user_id": str(telegram_user_id), "handler": "wfh", "is_active": 1},
		"name",
	)
	if existing:
		return frappe.get_doc("Telegram Conversation State", existing)

	state = frappe.get_doc({
		"doctype": "Telegram Conversation State",
		"chat_id": str(chat_id),
		"telegram_user_id": str(telegram_user_id),
		"handler": "wfh",
		"step": "select_from_date",
		"is_active": 1,
		"data": json.dumps({}),
		"expires_at": frappe.utils.add_to_date(None, hours=1),
	})
	state.insert(ignore_permissions=True)
	return state


def _clear_state(state):
	state.is_active = 0
	state.save(ignore_permissions=True)


def _update_state(state, step, data_update=None):
	state.step = step
	if data_update:
		current = json.loads(state.data or "{}")
		current.update(data_update)
		state.data = json.dumps(current)
	state.save(ignore_permissions=True)


def _get_state_data(state):
	return json.loads(state.data or "{}")


def _date_buttons(prefix, action):
	today = frappe.utils.today()
	tomorrow = frappe.utils.add_days(today, 1)
	day_after = frappe.utils.add_days(today, 2)

	import datetime

	today_dt = datetime.date.fromisoformat(today)
	days_until_monday = (7 - today_dt.weekday()) % 7
	if days_until_monday == 0:
		days_until_monday = 7
	next_monday = frappe.utils.add_days(today, days_until_monday)

	buttons = [
		[
			InlineKeyboardButton(f"Today ({today})", callback_data=f"{prefix}:{action}:{today}"),
			InlineKeyboardButton(f"Tomorrow ({tomorrow})", callback_data=f"{prefix}:{action}:{tomorrow}"),
		],
		[
			InlineKeyboardButton(f"Day After ({day_after})", callback_data=f"{prefix}:{action}:{day_after}"),
			InlineKeyboardButton(f"Next Monday ({next_monday})", callback_data=f"{prefix}:{action}:{next_monday}"),
		],
		[InlineKeyboardButton("Custom date...", callback_data=f"{prefix}:custom_{action}")],
	]
	return buttons


@register_command("/wfh", description="Apply for Work From Home")
def handle_wfh(message):
	chat_id = message["chat"]["id"]
	message_id = message["message_id"]

	try:
		set_message_reaction(chat_id, message_id, "👍")
	except Exception:
		pass

	employee = get_employee_from_user(frappe.session.user)
	if not employee:
		send_message(chat_id, "You are not linked to any active employee record.", reply_to_message_id=message_id)
		return

	state = _get_or_create_state(chat_id, message["from"]["id"])
	_update_state(state, "select_from_date", {"employee": employee})

	buttons = _date_buttons(CALLBACK_PREFIX, "from")
	buttons.append([InlineKeyboardButton("Cancel", callback_data=f"{CALLBACK_PREFIX}:cancel")])

	send_message(
		chat_id,
		"<b>Work From Home Request</b>\n\nSelect <b>from date</b>:",
		parse_mode="HTML",
		reply_markup=InlineKeyboardMarkup(buttons),
		reply_to_message_id=message_id,
	)


@register_callback(CALLBACK_PREFIX)
def handle_wfh_callback(callback_query, log):
	chat_id = log.chat_id
	telegram_user_id = log.telegram_user_id
	callback_query_id = log.callback_query_id
	callback_data = log.callback_data
	message_id = callback_query.get("message", {}).get("message_id")

	parts = callback_data.split(":", 2)
	if len(parts) < 2:
		answer_callback_query(callback_query_id, "Invalid action.")
		return

	action = parts[1]
	value = parts[2] if len(parts) > 2 else None

	state_name = frappe.db.get_value(
		"Telegram Conversation State",
		{"chat_id": str(chat_id), "telegram_user_id": str(telegram_user_id), "handler": "wfh", "is_active": 1},
		"name",
	)
	if not state_name:
		answer_callback_query(callback_query_id, "No active WFH request. Use /wfh to start.", show_alert=True)
		return

	state = frappe.get_doc("Telegram Conversation State", state_name)

	if action == "cancel":
		_clear_state(state)
		edit_message_text(chat_id, message_id, "WFH request cancelled.")
		answer_callback_query(callback_query_id, "Cancelled")
		return

	if action == "back":
		_handle_go_back(state, chat_id, message_id, callback_query_id)
	elif action == "custom_from":
		_update_state(state, "awaiting_from_date")
		answer_callback_query(callback_query_id)
		edit_message_text(
			chat_id, message_id,
			"<b>Work From Home Request</b>\n\nReply to this message with the <b>from date</b> (e.g. 25 Mar 2026):",
			parse_mode="HTML",
		)
	elif action == "custom_to":
		_update_state(state, "awaiting_to_date")
		answer_callback_query(callback_query_id)
		data = _get_state_data(state)
		edit_message_text(
			chat_id, message_id,
			f"<b>Work From Home Request</b>\n<b>From:</b> {data.get('from_date')}\n\nReply to this message with the <b>to date</b> (e.g. 28 Mar 2026):",
			parse_mode="HTML",
		)
	elif action == "from":
		_handle_from_date(state, chat_id, message_id, callback_query_id, value)
	elif action == "to":
		_handle_to_date(state, chat_id, message_id, callback_query_id, value)
	elif action == "half_day":
		_handle_half_day(state, chat_id, message_id, callback_query_id, value)
	elif action == "confirm":
		_handle_confirm(state, chat_id, message_id, callback_query_id)
	else:
		answer_callback_query(callback_query_id, "Unknown action.")


def _handle_go_back(state, chat_id, message_id, callback_query_id):
	answer_callback_query(callback_query_id)
	step = state.step
	data = _get_state_data(state)

	if step == "select_to_date":
		_update_state(state, "select_from_date")
		buttons = _date_buttons(CALLBACK_PREFIX, "from")
		buttons.append([InlineKeyboardButton("Cancel", callback_data=f"{CALLBACK_PREFIX}:cancel")])
		edit_message_text(
			chat_id, message_id,
			"<b>Work From Home Request</b>\n\nSelect <b>from date</b>:",
			parse_mode="HTML",
			reply_markup=InlineKeyboardMarkup(buttons),
		)

	elif step == "confirm":
		from_date = data.get("from_date")
		_update_state(state, "select_to_date")
		_handle_from_date(state, chat_id, message_id, callback_query_id, from_date)


def _handle_from_date(state, chat_id, message_id, callback_query_id, from_date):
	_update_state(state, "select_to_date", {"from_date": from_date})
	answer_callback_query(callback_query_id)

	same_day = from_date
	plus_one = frappe.utils.add_days(from_date, 1)
	plus_two = frappe.utils.add_days(from_date, 2)
	plus_four = frappe.utils.add_days(from_date, 4)

	buttons = [
		[
			InlineKeyboardButton(f"Same day ({same_day})", callback_data=f"{CALLBACK_PREFIX}:to:{same_day}"),
			InlineKeyboardButton(f"+1 day ({plus_one})", callback_data=f"{CALLBACK_PREFIX}:to:{plus_one}"),
		],
		[
			InlineKeyboardButton(f"+2 days ({plus_two})", callback_data=f"{CALLBACK_PREFIX}:to:{plus_two}"),
			InlineKeyboardButton(f"+4 days ({plus_four})", callback_data=f"{CALLBACK_PREFIX}:to:{plus_four}"),
		],
		[InlineKeyboardButton("Custom date...", callback_data=f"{CALLBACK_PREFIX}:custom_to")],
		[
			InlineKeyboardButton("← Go Back", callback_data=f"{CALLBACK_PREFIX}:back"),
			InlineKeyboardButton("Cancel", callback_data=f"{CALLBACK_PREFIX}:cancel"),
		],
	]

	edit_message_text(
		chat_id,
		message_id,
		f"<b>Work From Home Request</b>\n<b>From:</b> {from_date}\n\nSelect <b>to date</b>:",
		parse_mode="HTML",
		reply_markup=InlineKeyboardMarkup(buttons),
	)


def _handle_to_date(state, chat_id, message_id, callback_query_id, to_date):
	_update_state(state, "confirm", {"to_date": to_date})
	answer_callback_query(callback_query_id)
	_show_summary(state, chat_id, message_id)


def _show_summary(state, chat_id, message_id):
	data = _get_state_data(state)
	from_date = data["from_date"]
	to_date = data["to_date"]
	half_day = data.get("half_day", False)

	days = frappe.utils.date_diff(to_date, from_date) + 1
	half_day_label = "Yes" if half_day else "No"

	buttons = [
		[
			InlineKeyboardButton(f"{'Half Day' if not half_day else '✅ Half Day'}", callback_data=f"{CALLBACK_PREFIX}:half_day:1"),
			InlineKeyboardButton(f"{'✅ Full Day' if not half_day else 'Full Day'}", callback_data=f"{CALLBACK_PREFIX}:half_day:0"),
		],
		[InlineKeyboardButton("Confirm & Submit", callback_data=f"{CALLBACK_PREFIX}:confirm")],
		[
			InlineKeyboardButton("← Go Back", callback_data=f"{CALLBACK_PREFIX}:back"),
			InlineKeyboardButton("Cancel", callback_data=f"{CALLBACK_PREFIX}:cancel"),
		],
	]

	half_day_text = ""
	if half_day:
		half_day_text = f"\n<b>Half Day:</b> Yes ({from_date})"

	edit_message_text(
		chat_id,
		message_id,
		(
			f"<b>Work From Home Summary</b>\n\n"
			f"<b>From:</b> {from_date}\n"
			f"<b>To:</b> {to_date}\n"
			f"<b>Days:</b> {days}"
			f"{half_day_text}\n\n"
			f"Confirm and submit?"
		),
		parse_mode="HTML",
		reply_markup=InlineKeyboardMarkup(buttons),
	)


def _handle_half_day(state, chat_id, message_id, callback_query_id, value):
	half_day = value == "1"
	_update_state(state, "confirm", {"half_day": half_day})
	answer_callback_query(callback_query_id)
	_show_summary(state, chat_id, message_id)


def _handle_confirm(state, chat_id, message_id, callback_query_id):
	data = _get_state_data(state)
	_clear_state(state)

	try:
		doc_data = {
			"doctype": "Attendance Request",
			"employee": data["employee"],
			"from_date": data["from_date"],
			"to_date": data["to_date"],
			"reason": "Work From Home",
		}
		if data.get("half_day"):
			doc_data["half_day"] = 1
			doc_data["half_day_date"] = data["from_date"]

		doc = frappe.get_doc(doc_data)
		doc.insert()
		doc.submit()
		frappe.db.commit()

		answer_callback_query(callback_query_id, "WFH request submitted!")

		edit_message_text(
			chat_id,
			message_id,
			(
				f"<b>WFH Request Submitted</b>\n\n"
				f"<b>ID:</b> {doc.name}\n"
				f"<b>From:</b> {data['from_date']}\n"
				f"<b>To:</b> {data['to_date']}\n"
				f"<b>Status:</b> Submitted\n"
			),
			parse_mode="HTML",
		)
	except Exception as e:
		answer_callback_query(callback_query_id, "Failed to submit WFH request.", show_alert=True)
		edit_message_text(chat_id, message_id, f"Failed to submit WFH request:\n<code>{e}</code>", parse_mode="HTML")


def handle_wfh_date_text_input(state, chat_id, text):
	"""Handle typed date input for WFH flow."""
	text = text.strip()

	try:
		parsed = frappe.utils.getdate(text, parse_day_first=True)
		if not parsed:
			raise ValueError("Could not parse date")
		date_str = str(parsed)
	except Exception:
		send_message(chat_id, "Could not parse that date. Try formats like <code>25 Mar 2026</code>, <code>25-03-2026</code>, or <code>2026-03-25</code>.", parse_mode="HTML")
		return

	if state.step == "awaiting_from_date":
		_update_state(state, "select_to_date", {"from_date": date_str})
		data = _get_state_data(state)

		same_day = date_str
		plus_one = frappe.utils.add_days(date_str, 1)
		plus_two = frappe.utils.add_days(date_str, 2)
		plus_four = frappe.utils.add_days(date_str, 4)

		buttons = [
			[
				InlineKeyboardButton(f"Same day ({same_day})", callback_data=f"{CALLBACK_PREFIX}:to:{same_day}"),
				InlineKeyboardButton(f"+1 day ({plus_one})", callback_data=f"{CALLBACK_PREFIX}:to:{plus_one}"),
			],
			[
				InlineKeyboardButton(f"+2 days ({plus_two})", callback_data=f"{CALLBACK_PREFIX}:to:{plus_two}"),
				InlineKeyboardButton(f"+4 days ({plus_four})", callback_data=f"{CALLBACK_PREFIX}:to:{plus_four}"),
			],
			[InlineKeyboardButton("Custom date...", callback_data=f"{CALLBACK_PREFIX}:custom_to")],
			[
				InlineKeyboardButton("← Go Back", callback_data=f"{CALLBACK_PREFIX}:back"),
				InlineKeyboardButton("Cancel", callback_data=f"{CALLBACK_PREFIX}:cancel"),
			],
		]

		send_message(
			chat_id,
			f"<b>Work From Home Request</b>\n<b>From:</b> {date_str}\n\nSelect <b>to date</b>:",
			parse_mode="HTML",
			reply_markup=InlineKeyboardMarkup(buttons),
		)

	elif state.step == "awaiting_to_date":
		data = _get_state_data(state)
		from_date = data["from_date"]
		_update_state(state, "confirm", {"to_date": date_str})

		days = frappe.utils.date_diff(date_str, from_date) + 1

		buttons = [
			[InlineKeyboardButton("Confirm & Submit", callback_data=f"{CALLBACK_PREFIX}:confirm")],
			[
				InlineKeyboardButton("← Go Back", callback_data=f"{CALLBACK_PREFIX}:back"),
				InlineKeyboardButton("Cancel", callback_data=f"{CALLBACK_PREFIX}:cancel"),
			],
		]

		send_message(
			chat_id,
			(
				f"<b>Work From Home Summary</b>\n\n"
				f"<b>From:</b> {from_date}\n"
				f"<b>To:</b> {date_str}\n"
				f"<b>Days:</b> {days}\n\n"
				f"Confirm and submit?"
			),
			parse_mode="HTML",
			reply_markup=InlineKeyboardMarkup(buttons),
		)
