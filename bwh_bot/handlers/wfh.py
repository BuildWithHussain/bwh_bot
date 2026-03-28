import frappe
from telegram import InlineKeyboardButton

from bwh_bot.conversation import BotConversation
from bwh_bot.telegram_utils import answer_callback_query, edit_message_text, send_message
from bwh_bot.ui import from_date_buttons, make_keyboard, nav_buttons, to_date_buttons


class WFHConversation(BotConversation):
	handler_name = "wfh"
	callback_prefix = "wfh"
	command = "/wfh"
	command_description = "Apply for Work From Home"
	title = "Work From Home Request"

	def on_start(self, message, state, employee):
		chat_id = message["chat"]["id"]
		message_id = message["message_id"]
		message_thread_id = message.get("message_thread_id")

		self.update_state(state, "select_from_date")
		send_message(
			chat_id,
			f"<b>{self.title}</b>\n\nSelect <b>from date</b>:",
			parse_mode="HTML",
			reply_markup=make_keyboard(
				from_date_buttons(self.callback_prefix, include_today=True),
				nav_buttons(self.callback_prefix, show_back=False),
			),
			reply_to_message_id=message_id,
			message_thread_id=message_thread_id,
		)

	def on_action(self, action, value, state, ctx):
		chat_id, message_id, cqid = ctx["chat_id"], ctx["message_id"], ctx["callback_query_id"]

		if action == "from":
			self.update_state(state, "select_to_date", {"from_date": value})
			answer_callback_query(cqid)
			edit_message_text(
				chat_id, message_id,
				f"<b>{self.title}</b>\n<b>From:</b> {value}\n\nSelect <b>to date</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(to_date_buttons(self.callback_prefix, value), nav_buttons(self.callback_prefix)),
			)

		elif action == "to":
			self.update_state(state, "confirm", {"to_date": value})
			answer_callback_query(cqid)
			self._show_summary(state, chat_id, message_id)

		elif action == "half_day":
			half_day = value == "1"
			self.update_state(state, "confirm", {"half_day": half_day})
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

		if step == "select_to_date":
			self.update_state(state, "select_from_date")
			edit_message_text(
				chat_id, message_id,
				f"<b>{self.title}</b>\n\nSelect <b>from date</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(
					from_date_buttons(self.callback_prefix, include_today=True),
					nav_buttons(self.callback_prefix, show_back=False),
				),
			)

		elif step == "confirm":
			self.update_state(state, "select_to_date")
			edit_message_text(
				chat_id, message_id,
				f"<b>{self.title}</b>\n<b>From:</b> {data['from_date']}\n\nSelect <b>to date</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(to_date_buttons(self.callback_prefix, data["from_date"]), nav_buttons(self.callback_prefix)),
			)

	def on_text_input(self, state, chat_id, date_str):
		data = self.get_data(state)
		message_thread_id = data.get("message_thread_id")

		if state.step == "awaiting_from_date":
			self.update_state(state, "select_to_date", {"from_date": date_str})
			send_message(
				chat_id,
				f"<b>{self.title}</b>\n<b>From:</b> {date_str}\n\nSelect <b>to date</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(to_date_buttons(self.callback_prefix, date_str), nav_buttons(self.callback_prefix)),
				message_thread_id=message_thread_id,
			)

		elif state.step == "awaiting_to_date":
			self.update_state(state, "confirm", {"to_date": date_str})
			data = self.get_data(state)
			days = frappe.utils.date_diff(date_str, data["from_date"]) + 1
			send_message(
				chat_id,
				(
					f"<b>Work From Home Summary</b>\n\n"
					f"<b>From:</b> {data['from_date']}\n"
					f"<b>To:</b> {date_str}\n"
					f"<b>Days:</b> {days}\n\n"
					f"Confirm and submit?"
				),
				parse_mode="HTML",
				reply_markup=make_keyboard(self._summary_buttons(data)),
				message_thread_id=message_thread_id,
			)

	def _build_header(self, data):
		parts = [f"<b>{self.title}</b>"]
		if data.get("from_date"):
			parts.append(f"<b>From:</b> {data['from_date']}")
		return "\n".join(parts)

	def _summary_buttons(self, data):
		half_day = data.get("half_day", False)
		p = self.callback_prefix
		return [
			[
				InlineKeyboardButton(f"{'Half Day' if not half_day else '✅ Half Day'}", callback_data=f"{p}:half_day:1"),
				InlineKeyboardButton(f"{'✅ Full Day' if not half_day else 'Full Day'}", callback_data=f"{p}:half_day:0"),
			],
			[InlineKeyboardButton("Confirm & Submit", callback_data=f"{p}:confirm")],
		] + nav_buttons(p)

	def _show_summary(self, state, chat_id, message_id):
		data = self.get_data(state)
		days = frappe.utils.date_diff(data["to_date"], data["from_date"]) + 1
		half_day = data.get("half_day", False)

		half_day_text = ""
		if half_day:
			half_day_text = f"\n<b>Half Day:</b> Yes ({data['from_date']})"

		edit_message_text(
			chat_id, message_id,
			(
				f"<b>Work From Home Summary</b>\n\n"
				f"<b>From:</b> {data['from_date']}\n"
				f"<b>To:</b> {data['to_date']}\n"
				f"<b>Days:</b> {days}"
				f"{half_day_text}\n\n"
				f"Confirm and submit?"
			),
			parse_mode="HTML",
			reply_markup=make_keyboard(self._summary_buttons(data)),
		)

	def _handle_confirm(self, state, ctx):
		data = self.get_data(state)
		self.clear_state(state)
		chat_id, message_id, cqid = ctx["chat_id"], ctx["message_id"], ctx["callback_query_id"]

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

			frappe.db.savepoint("before_attendance_request")
			doc = frappe.get_doc(doc_data)
			doc.insert()
			doc.submit()
			frappe.db.commit()

			answer_callback_query(cqid, "WFH request submitted!")
			edit_message_text(
				chat_id, message_id,
				(
					f"<b>WFH Request Submitted</b>\n\n"
					f"<b>Employee:</b> {doc.employee_name}\n"
					f"<b>ID:</b> {doc.name}\n"
					f"<b>From:</b> {data['from_date']}\n"
					f"<b>To:</b> {data['to_date']}\n"
					f"<b>Status:</b> Submitted\n"
				),
				parse_mode="HTML",
			)
		except Exception as e:
			frappe.db.rollback(save_point="before_attendance_request")
			answer_callback_query(cqid, "Failed to submit WFH request.", show_alert=True)
			edit_message_text(chat_id, message_id, f"Failed to submit WFH request:\n<code>{e}</code>", parse_mode="HTML")
