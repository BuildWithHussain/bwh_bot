import json

import frappe
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bwh_bot.api.telegram import register_callback, register_command
from bwh_bot.telegram_utils import (
	answer_callback_query,
	edit_message_text,
	get_employee_from_user,
	get_leave_types_for_employee,
	send_message,
	set_message_reaction,
)

# Callback data format: la:<action>:<value>
CALLBACK_PREFIX = "la"


def _get_or_create_state(chat_id, telegram_user_id):
	"""Get active conversation state or create a new one."""
	existing = frappe.db.get_value(
		"Telegram Conversation State",
		{"chat_id": str(chat_id), "telegram_user_id": str(telegram_user_id), "handler": "leave", "is_active": 1},
		"name",
	)
	if existing:
		return frappe.get_doc("Telegram Conversation State", existing)

	state = frappe.get_doc({
		"doctype": "Telegram Conversation State",
		"chat_id": str(chat_id),
		"telegram_user_id": str(telegram_user_id),
		"handler": "leave",
		"step": "select_leave_type",
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


@register_command("/leave_application", description="Apply for leave")
def handle_leave_application(message):
	chat_id = message["chat"]["id"]
	message_id = message["message_id"]

	# React to acknowledge
	try:
		set_message_reaction(chat_id, message_id, "👍")
	except Exception:
		pass

	employee = get_employee_from_user(frappe.session.user)
	if not employee:
		send_message(chat_id, "You are not linked to any active employee record.", reply_to_message_id=message_id)
		return

	leave_types = get_leave_types_for_employee(employee)
	if not leave_types:
		send_message(chat_id, "You have no leave allocations for the current period.", reply_to_message_id=message_id)
		return

	# Create conversation state
	state = _get_or_create_state(chat_id, message["from"]["id"])
	_update_state(state, "select_leave_type", {"employee": employee})

	# Build inline keyboard with leave types
	buttons = []
	for lt in leave_types:
		balance = int(lt['balance']) if lt['balance'] == int(lt['balance']) else lt['balance']
		label = f"{lt['leave_type']} ({balance} days)"
		buttons.append([InlineKeyboardButton(label, callback_data=f"{CALLBACK_PREFIX}:type:{lt['leave_type']}")])

	buttons.append([InlineKeyboardButton("Cancel", callback_data=f"{CALLBACK_PREFIX}:cancel")])
	reply_markup = InlineKeyboardMarkup(buttons)

	send_message(
		chat_id,
		"<b>Apply for Leave</b>\n\nSelect leave type:",
		parse_mode="HTML",
		reply_markup=reply_markup,
		reply_to_message_id=message_id,
	)


def handle_date_text_input(state, chat_id, text):
	"""Handle typed date input from user."""
	text = text.strip()

	# Try to parse the date
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
			f"<b>Leave Type:</b> {data.get('leave_type')}\n<b>From:</b> {date_str}\n\nSelect <b>to date</b>:",
			parse_mode="HTML",
			reply_markup=InlineKeyboardMarkup(buttons),
		)

	elif state.step == "awaiting_to_date":
		data = _get_state_data(state)
		from_date = data["from_date"]
		leave_type = data["leave_type"]
		_update_state(state, "confirm", {"to_date": date_str})

		days = frappe.utils.date_diff(date_str, from_date) + 1

		buttons = [
			[InlineKeyboardButton("Confirm", callback_data=f"{CALLBACK_PREFIX}:confirm")],
			[
				InlineKeyboardButton("← Go Back", callback_data=f"{CALLBACK_PREFIX}:back"),
				InlineKeyboardButton("Cancel", callback_data=f"{CALLBACK_PREFIX}:cancel"),
			],
		]

		send_message(
			chat_id,
			(
				f"<b>Leave Application Summary</b>\n\n"
				f"<b>Type:</b> {leave_type}\n"
				f"<b>From:</b> {from_date}\n"
				f"<b>To:</b> {date_str}\n"
				f"<b>Days:</b> {days}\n\n"
				f"Confirm?"
			),
			parse_mode="HTML",
			reply_markup=InlineKeyboardMarkup(buttons),
		)


@register_callback(CALLBACK_PREFIX)
def handle_leave_callback(callback_query, log):
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

	# Get active state
	state_name = frappe.db.get_value(
		"Telegram Conversation State",
		{"chat_id": str(chat_id), "telegram_user_id": str(telegram_user_id), "handler": "leave", "is_active": 1},
		"name",
	)
	if not state_name:
		answer_callback_query(callback_query_id, "No active leave application. Use /leave_application to start.", show_alert=True)
		return

	state = frappe.get_doc("Telegram Conversation State", state_name)

	if action == "cancel":
		_clear_state(state)
		edit_message_text(chat_id, message_id, "Leave application cancelled.")
		answer_callback_query(callback_query_id, "Cancelled")
		return

	if action == "back":
		_handle_go_back(state, chat_id, message_id, callback_query_id)
	elif action == "custom_from":
		_update_state(state, "awaiting_from_date")
		answer_callback_query(callback_query_id)
		data = _get_state_data(state)
		edit_message_text(
			chat_id, message_id,
			f"<b>Leave Type:</b> {data.get('leave_type')}\n\nReply to this message with the <b>from date</b> (e.g. 25 Mar 2026):",
			parse_mode="HTML",
		)
	elif action == "custom_to":
		_update_state(state, "awaiting_to_date")
		answer_callback_query(callback_query_id)
		data = _get_state_data(state)
		edit_message_text(
			chat_id, message_id,
			f"<b>Leave Type:</b> {data.get('leave_type')}\n<b>From:</b> {data.get('from_date')}\n\nReply to this message with the <b>to date</b> (e.g. 28 Mar 2026):",
			parse_mode="HTML",
		)
	elif action == "type":
		_handle_leave_type_selected(state, chat_id, message_id, callback_query_id, value)
	elif action == "from":
		_handle_from_date_selected(state, chat_id, message_id, callback_query_id, value)
	elif action == "to":
		_handle_to_date_selected(state, chat_id, message_id, callback_query_id, value)
	elif action == "confirm":
		_handle_confirm(state, chat_id, message_id, callback_query_id)
	else:
		answer_callback_query(callback_query_id, "Unknown action.")


def _handle_go_back(state, chat_id, message_id, callback_query_id):
	answer_callback_query(callback_query_id)
	step = state.step
	data = _get_state_data(state)

	if step == "select_from_date":
		# Go back to leave type selection
		employee = data.get("employee")
		leave_types = get_leave_types_for_employee(employee)
		_update_state(state, "select_leave_type")

		buttons = []
		for lt in leave_types:
			balance = int(lt["balance"]) if lt["balance"] == int(lt["balance"]) else lt["balance"]
			label = f"{lt['leave_type']} ({balance} days)"
			buttons.append([InlineKeyboardButton(label, callback_data=f"{CALLBACK_PREFIX}:type:{lt['leave_type']}")])
		buttons.append([InlineKeyboardButton("Cancel", callback_data=f"{CALLBACK_PREFIX}:cancel")])

		edit_message_text(
			chat_id, message_id,
			"<b>Apply for Leave</b>\n\nSelect leave type:",
			parse_mode="HTML",
			reply_markup=InlineKeyboardMarkup(buttons),
		)

	elif step == "select_to_date":
		# Go back to from date selection — re-render with leave type already selected
		leave_type = data.get("leave_type")
		_update_state(state, "select_from_date")
		_handle_leave_type_selected(state, chat_id, message_id, callback_query_id, leave_type)

	elif step == "confirm":
		# Go back to to date selection — re-render with from date already selected
		from_date = data.get("from_date")
		_update_state(state, "select_to_date")
		_handle_from_date_selected(state, chat_id, message_id, callback_query_id, from_date)


def _handle_leave_type_selected(state, chat_id, message_id, callback_query_id, leave_type):
	_update_state(state, "select_from_date", {"leave_type": leave_type})
	answer_callback_query(callback_query_id)

	today = frappe.utils.today()
	tomorrow = frappe.utils.add_days(today, 1)
	day_after = frappe.utils.add_days(today, 2)

	# Find next Monday
	import datetime

	today_dt = datetime.date.fromisoformat(today)
	days_until_monday = (7 - today_dt.weekday()) % 7
	if days_until_monday == 0:
		days_until_monday = 7
	next_monday = frappe.utils.add_days(today, days_until_monday)

	buttons = [
		[
			InlineKeyboardButton(f"Tomorrow ({tomorrow})", callback_data=f"{CALLBACK_PREFIX}:from:{tomorrow}"),
			InlineKeyboardButton(f"Day After ({day_after})", callback_data=f"{CALLBACK_PREFIX}:from:{day_after}"),
		],
		[InlineKeyboardButton(f"Next Monday ({next_monday})", callback_data=f"{CALLBACK_PREFIX}:from:{next_monday}")],
		[InlineKeyboardButton("Custom date...", callback_data=f"{CALLBACK_PREFIX}:custom_from")],
		[
			InlineKeyboardButton("← Go Back", callback_data=f"{CALLBACK_PREFIX}:back"),
			InlineKeyboardButton("Cancel", callback_data=f"{CALLBACK_PREFIX}:cancel"),
		],
	]

	edit_message_text(
		chat_id,
		message_id,
		f"<b>Leave Type:</b> {leave_type}\n\nSelect <b>from date</b>:",
		parse_mode="HTML",
		reply_markup=InlineKeyboardMarkup(buttons),
	)


def _handle_from_date_selected(state, chat_id, message_id, callback_query_id, from_date):
	_update_state(state, "select_to_date", {"from_date": from_date})
	answer_callback_query(callback_query_id)

	data = _get_state_data(state)
	# Offer same day, +1, +2 from the from_date
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
		f"<b>Leave Type:</b> {data.get('leave_type')}\n<b>From:</b> {from_date}\n\nSelect <b>to date</b>:",
		parse_mode="HTML",
		reply_markup=InlineKeyboardMarkup(buttons),
	)


def _handle_to_date_selected(state, chat_id, message_id, callback_query_id, to_date):
	_update_state(state, "confirm", {"to_date": to_date})
	answer_callback_query(callback_query_id)

	data = _get_state_data(state)
	from_date = data["from_date"]
	leave_type = data["leave_type"]

	# Calculate days
	days = frappe.utils.date_diff(to_date, from_date) + 1

	buttons = [
		[
			InlineKeyboardButton("Confirm", callback_data=f"{CALLBACK_PREFIX}:confirm"),
		],
		[
			InlineKeyboardButton("← Go Back", callback_data=f"{CALLBACK_PREFIX}:back"),
			InlineKeyboardButton("Cancel", callback_data=f"{CALLBACK_PREFIX}:cancel"),
		],
	]

	edit_message_text(
		chat_id,
		message_id,
		(
			f"<b>Leave Application Summary</b>\n\n"
			f"<b>Type:</b> {leave_type}\n"
			f"<b>From:</b> {from_date}\n"
			f"<b>To:</b> {to_date}\n"
			f"<b>Days:</b> {days}\n\n"
			f"Confirm?"
		),
		parse_mode="HTML",
		reply_markup=InlineKeyboardMarkup(buttons),
	)


def _handle_confirm(state, chat_id, message_id, callback_query_id):
	data = _get_state_data(state)
	_clear_state(state)

	try:
		leave_app = frappe.get_doc({
			"doctype": "Leave Application",
			"employee": data["employee"],
			"leave_type": data["leave_type"],
			"from_date": data["from_date"],
			"to_date": data["to_date"],
			"status": "Open",
			"follow_via_email": 0,
		})
		leave_app.insert()
		frappe.db.commit()

		answer_callback_query(callback_query_id, "Leave application created!")

		edit_message_text(
			chat_id,
			message_id,
			(
				f"<b>Leave Application Created</b>\n\n"
				f"<b>ID:</b> {leave_app.name}\n"
				f"<b>Type:</b> {data['leave_type']}\n"
				f"<b>From:</b> {data['from_date']}\n"
				f"<b>To:</b> {data['to_date']}\n"
				f"<b>Status:</b> Pending Approval\n"
			),
			parse_mode="HTML",
		)
	except Exception as e:
		answer_callback_query(callback_query_id, "Failed to create leave application.", show_alert=True)
		edit_message_text(chat_id, message_id, f"Failed to create leave application:\n<code>{e}</code>", parse_mode="HTML")


# --- Doc Event Handler ---


def on_leave_application_update(doc, method):
	"""Called via doc_events hook when Leave Application is updated."""
	if not doc.has_value_changed("status"):
		return

	if doc.status not in ("Approved", "Rejected"):
		return

	employee_user = frappe.db.get_value("Employee", doc.employee, "user_id")
	if not employee_user:
		return

	from bwh_bot.telegram_utils import get_telegram_user_for_frappe_user

	telegram_user = get_telegram_user_for_frappe_user(employee_user)
	if not telegram_user:
		return

	# Send to all whitelisted chats
	settings = frappe.get_single("BWH Bot Settings")
	status_emoji = "✅" if doc.status == "Approved" else "❌"

	message = (
		f"{status_emoji} <b>Leave {doc.status}</b>\n\n"
		f"<b>ID:</b> {doc.name}\n"
		f"<b>Employee:</b> {doc.employee_name}\n"
		f"<b>Type:</b> {doc.leave_type}\n"
		f"<b>From:</b> {doc.from_date}\n"
		f"<b>To:</b> {doc.to_date}\n"
		f"<b>Total Days:</b> {doc.total_leave_days}"
	)

	for chat in settings.whitelisted_chats:
		try:
			send_message(chat.chat_id, message, parse_mode="HTML")
		except Exception:
			frappe.log_error(f"Failed to send Telegram notification to chat {chat.chat_id}")
