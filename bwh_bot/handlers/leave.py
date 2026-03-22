import frappe
from telegram import InlineKeyboardButton

from bwh_bot.conversation import BotConversation
from bwh_bot.telegram_utils import (
	answer_callback_query,
	edit_message_text,
	get_leave_types_for_employee,
	send_message,
)
from bwh_bot.ui import confirm_buttons, from_date_buttons, make_keyboard, nav_buttons, to_date_buttons


class LeaveConversation(BotConversation):
	handler_name = "leave"
	callback_prefix = "la"
	command = "/leave_application"
	command_description = "Apply for leave"
	title = "Apply for Leave"

	def on_start(self, message, state, employee):
		chat_id = message["chat"]["id"]
		message_id = message["message_id"]

		leave_types = get_leave_types_for_employee(employee)
		if not leave_types:
			send_message(chat_id, "You have no leave allocations for the current period.", reply_to_message_id=message_id)
			self.clear_state(state)
			return

		self.update_state(state, "select_leave_type")
		buttons = self._leave_type_buttons(leave_types)

		send_message(
			chat_id,
			f"<b>{self.title}</b>\n\nSelect leave type:",
			parse_mode="HTML",
			reply_markup=make_keyboard(buttons, nav_buttons(self.callback_prefix, show_back=False)),
			reply_to_message_id=message_id,
		)

	def on_action(self, action, value, state, ctx):
		chat_id, message_id, cqid = ctx["chat_id"], ctx["message_id"], ctx["callback_query_id"]

		if action == "type":
			self.update_state(state, "select_from_date", {"leave_type": value})
			answer_callback_query(cqid)
			edit_message_text(
				chat_id, message_id,
				f"<b>Leave Type:</b> {value}\n\nSelect <b>from date</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(from_date_buttons(self.callback_prefix), nav_buttons(self.callback_prefix)),
			)

		elif action == "from":
			self.update_state(state, "select_to_date", {"from_date": value})
			answer_callback_query(cqid)
			data = self.get_data(state)
			edit_message_text(
				chat_id, message_id,
				f"<b>Leave Type:</b> {data['leave_type']}\n<b>From:</b> {value}\n\nSelect <b>to date</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(to_date_buttons(self.callback_prefix, value), nav_buttons(self.callback_prefix)),
			)

		elif action == "to":
			self.update_state(state, "confirm", {"to_date": value})
			answer_callback_query(cqid)
			self._show_summary(state, chat_id, message_id)

		elif action == "confirm":
			self._handle_confirm(state, ctx)

		else:
			answer_callback_query(cqid, "Unknown action.")

	def on_back(self, state, ctx):
		chat_id, message_id = ctx["chat_id"], ctx["message_id"]
		data = self.get_data(state)
		step = state.step

		if step == "select_from_date":
			employee = data.get("employee")
			leave_types = get_leave_types_for_employee(employee)
			self.update_state(state, "select_leave_type")
			buttons = self._leave_type_buttons(leave_types)
			edit_message_text(
				chat_id, message_id,
				f"<b>{self.title}</b>\n\nSelect leave type:",
				parse_mode="HTML",
				reply_markup=make_keyboard(buttons, nav_buttons(self.callback_prefix, show_back=False)),
			)

		elif step == "select_to_date":
			self.update_state(state, "select_from_date")
			edit_message_text(
				chat_id, message_id,
				f"<b>Leave Type:</b> {data['leave_type']}\n\nSelect <b>from date</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(from_date_buttons(self.callback_prefix), nav_buttons(self.callback_prefix)),
			)

		elif step == "confirm":
			self.update_state(state, "select_to_date")
			edit_message_text(
				chat_id, message_id,
				f"<b>Leave Type:</b> {data['leave_type']}\n<b>From:</b> {data['from_date']}\n\nSelect <b>to date</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(to_date_buttons(self.callback_prefix, data["from_date"]), nav_buttons(self.callback_prefix)),
			)

	def on_text_input(self, state, chat_id, date_str):
		if state.step == "awaiting_from_date":
			self.update_state(state, "select_to_date", {"from_date": date_str})
			data = self.get_data(state)
			send_message(
				chat_id,
				f"<b>Leave Type:</b> {data['leave_type']}\n<b>From:</b> {date_str}\n\nSelect <b>to date</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(to_date_buttons(self.callback_prefix, date_str), nav_buttons(self.callback_prefix)),
			)

		elif state.step == "awaiting_to_date":
			self.update_state(state, "confirm", {"to_date": date_str})
			data = self.get_data(state)
			days = frappe.utils.date_diff(date_str, data["from_date"]) + 1
			send_message(
				chat_id,
				(
					f"<b>Leave Application Summary</b>\n\n"
					f"<b>Type:</b> {data['leave_type']}\n"
					f"<b>From:</b> {data['from_date']}\n"
					f"<b>To:</b> {date_str}\n"
					f"<b>Days:</b> {days}\n\n"
					f"Confirm?"
				),
				parse_mode="HTML",
				reply_markup=make_keyboard(confirm_buttons(self.callback_prefix)),
			)

	def _build_header(self, data):
		parts = [f"<b>{self.title}</b>"]
		if data.get("leave_type"):
			parts.append(f"<b>Leave Type:</b> {data['leave_type']}")
		if data.get("from_date"):
			parts.append(f"<b>From:</b> {data['from_date']}")
		return "\n".join(parts)

	def _leave_type_buttons(self, leave_types):
		buttons = []
		for lt in leave_types:
			balance = int(lt["balance"]) if lt["balance"] == int(lt["balance"]) else lt["balance"]
			label = f"{lt['leave_type']} ({balance} days)"
			buttons.append([InlineKeyboardButton(label, callback_data=f"{self.callback_prefix}:type:{lt['leave_type']}")])
		return buttons

	def _show_summary(self, state, chat_id, message_id):
		data = self.get_data(state)
		days = frappe.utils.date_diff(data["to_date"], data["from_date"]) + 1
		edit_message_text(
			chat_id, message_id,
			(
				f"<b>Leave Application Summary</b>\n\n"
				f"<b>Type:</b> {data['leave_type']}\n"
				f"<b>From:</b> {data['from_date']}\n"
				f"<b>To:</b> {data['to_date']}\n"
				f"<b>Days:</b> {days}\n\n"
				f"Confirm?"
			),
			parse_mode="HTML",
			reply_markup=make_keyboard(confirm_buttons(self.callback_prefix)),
		)

	def _handle_confirm(self, state, ctx):
		data = self.get_data(state)
		self.clear_state(state)
		chat_id, message_id, cqid = ctx["chat_id"], ctx["message_id"], ctx["callback_query_id"]

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

			answer_callback_query(cqid, "Leave application created!")
			edit_message_text(
				chat_id, message_id,
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
			answer_callback_query(cqid, "Failed to create leave application.", show_alert=True)
			edit_message_text(chat_id, message_id, f"Failed to create leave application:\n<code>{e}</code>", parse_mode="HTML")


# --- Doc Event Handler ---


def on_leave_application_update(doc, method):
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
