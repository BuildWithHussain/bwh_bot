import frappe
from frappe.utils import flt
from telegram import InlineKeyboardButton

from bwh_bot.conversation import BotConversation
from bwh_bot.telegram_utils import answer_callback_query, edit_message_text, send_message
from bwh_bot.ui import confirm_buttons, expense_date_buttons, make_keyboard, nav_buttons


class PettyCashConversation(BotConversation):
	handler_name = "petty_cash"
	callback_prefix = "pc"
	command = "/use_petty_cash"
	command_description = "Record a petty cash expense"
	title = "Petty Cash Usage"

	def on_start(self, message, state, employee):
		chat_id = message["chat"]["id"]
		message_id = message["message_id"]
		message_thread_id = message.get("message_thread_id")

		self.update_state(state, "awaiting_amount")
		send_message(
			chat_id,
			f"<b>{self.title}</b>\n\nReply with the <b>amount</b>:",
			parse_mode="HTML",
			reply_to_message_id=message_id,
			message_thread_id=message_thread_id,
		)

	def on_raw_text_input(self, state, chat_id, text):
		data = self.get_data(state)
		message_thread_id = data.get("message_thread_id")

		if state.step == "awaiting_amount":
			amount = flt(text)
			if amount <= 0:
				send_message(
					chat_id,
					"Please enter a valid amount greater than 0.",
					message_thread_id=message_thread_id,
				)
				return

			self.update_state(state, "select_category", {"amount": amount})
			categories = _get_categories()
			if not categories:
				send_message(
					chat_id,
					"No petty cash categories found. Please contact your administrator.",
					message_thread_id=message_thread_id,
				)
				self.clear_state(state)
				return

			data = self.get_data(state)
			send_message(
				chat_id,
				f"{self._build_header(data)}\n\nSelect <b>category</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(
					_category_buttons(self.callback_prefix, categories),
					nav_buttons(self.callback_prefix, show_back=False),
				),
				message_thread_id=message_thread_id,
			)

		elif state.step == "awaiting_remarks":
			self.update_state(state, "select_date", {"remarks": text})
			data = self.get_data(state)
			send_message(
				chat_id,
				f"{self._build_header(data)}\n\nSelect <b>expense date</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(
					expense_date_buttons(self.callback_prefix),
					nav_buttons(self.callback_prefix),
				),
				message_thread_id=message_thread_id,
			)

	def on_action(self, action, value, state, ctx):
		chat_id, message_id, cqid = ctx["chat_id"], ctx["message_id"], ctx["callback_query_id"]

		if action == "cat":
			self.update_state(state, "awaiting_remarks", {"category": value})
			answer_callback_query(cqid)
			data = self.get_data(state)
			edit_message_text(
				chat_id,
				message_id,
				f"{self._build_header(data)}\n\nReply with a short <b>description/remarks</b>:",
				parse_mode="HTML",
			)

		elif action == "date":
			self.update_state(state, "confirm", {"expense_date": value})
			answer_callback_query(cqid)
			self._show_summary(state, chat_id, message_id)

		elif action == "custom_date":
			self.update_state(state, "awaiting_custom_date")
			answer_callback_query(cqid)
			data = self.get_data(state)
			edit_message_text(
				chat_id,
				message_id,
				f"{self._build_header(data)}\n\nReply with the <b>expense date</b> (e.g. 25 Mar 2026):",
				parse_mode="HTML",
			)

		elif action == "confirm":
			self._handle_confirm(state, ctx)

		else:
			answer_callback_query(cqid, "Unknown action.")

	def on_text_input(self, state, chat_id, date_str):
		"""Handle parsed date from awaiting_custom_date step."""
		data = self.get_data(state)
		message_thread_id = data.get("message_thread_id")

		if state.step == "awaiting_custom_date":
			self.update_state(state, "confirm", {"expense_date": date_str})
			data = self.get_data(state)
			send_message(
				chat_id,
				self._summary_text(data),
				parse_mode="HTML",
				reply_markup=make_keyboard(confirm_buttons(self.callback_prefix, label="Confirm & Save")),
				message_thread_id=message_thread_id,
			)

	def on_back(self, state, ctx):
		chat_id, message_id = ctx["chat_id"], ctx["message_id"]
		data = self.get_data(state)
		step = state.step

		if step == "select_category":
			self.update_state(state, "awaiting_amount")
			edit_message_text(
				chat_id,
				message_id,
				f"<b>{self.title}</b>\n\nReply with the <b>amount</b>:",
				parse_mode="HTML",
			)

		elif step == "awaiting_remarks":
			categories = _get_categories()
			self.update_state(state, "select_category")
			edit_message_text(
				chat_id,
				message_id,
				f"{self._build_header(data)}\n\nSelect <b>category</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(
					_category_buttons(self.callback_prefix, categories),
					nav_buttons(self.callback_prefix, show_back=False),
				),
			)

		elif step == "select_date":
			self.update_state(state, "awaiting_remarks")
			edit_message_text(
				chat_id,
				message_id,
				f"{self._build_header(data)}\n\nReply with a short <b>description/remarks</b>:",
				parse_mode="HTML",
			)

		elif step == "confirm":
			self.update_state(state, "select_date")
			edit_message_text(
				chat_id,
				message_id,
				f"{self._build_header(data)}\n\nSelect <b>expense date</b>:",
				parse_mode="HTML",
				reply_markup=make_keyboard(
					expense_date_buttons(self.callback_prefix),
					nav_buttons(self.callback_prefix),
				),
			)

	def _build_header(self, data):
		parts = [f"<b>{self.title}</b>"]
		if data.get("amount"):
			parts.append(f"<b>Amount:</b> {data['amount']}")
		if data.get("category"):
			parts.append(f"<b>Category:</b> {data['category']}")
		if data.get("remarks"):
			parts.append(f"<b>Remarks:</b> {data['remarks']}")
		if data.get("expense_date"):
			parts.append(f"<b>Expense Date:</b> {data['expense_date']}")
		return "\n".join(parts)

	def _summary_text(self, data):
		return (
			f"<b>Petty Cash Usage Summary</b>\n\n"
			f"<b>Amount:</b> {data['amount']}\n"
			f"<b>Category:</b> {data['category']}\n"
			f"<b>Remarks:</b> {data.get('remarks', '-')}\n"
			f"<b>Expense Date:</b> {data['expense_date']}\n\n"
			f"Confirm and save?"
		)

	def _show_summary(self, state, chat_id, message_id):
		data = self.get_data(state)
		edit_message_text(
			chat_id,
			message_id,
			self._summary_text(data),
			parse_mode="HTML",
			reply_markup=make_keyboard(confirm_buttons(self.callback_prefix, label="Confirm & Save")),
		)

	def _handle_confirm(self, state, ctx):
		data = self.get_data(state)
		self.clear_state(state)
		chat_id, message_id, cqid = ctx["chat_id"], ctx["message_id"], ctx["callback_query_id"]

		try:
			frappe.db.savepoint("before_petty_cash_usage")
			doc = frappe.get_doc(
				{
					"doctype": "Petty Cash Usage",
					"employee": data["employee"],
					"amount": data["amount"],
					"category": data["category"],
					"remarks": data.get("remarks"),
					"expense_date": data["expense_date"],
				}
			)
			doc.insert()
			frappe.db.commit()

			answer_callback_query(cqid, "Petty cash entry saved!")
			edit_message_text(
				chat_id,
				message_id,
				(
					f"<b>Petty Cash Entry Saved</b>\n\n"
					f"<b>ID:</b> {doc.name}\n"
					f"<b>Employee:</b> {doc.employee_name}\n"
					f"<b>Amount:</b> {doc.amount}\n"
					f"<b>Category:</b> {doc.category}\n"
					f"<b>Remarks:</b> {doc.remarks or '-'}\n"
					f"<b>Expense Date:</b> {doc.expense_date}\n"
					f"<b>Status:</b> Draft\n"
				),
				parse_mode="HTML",
			)
		except Exception as e:
			frappe.db.rollback(save_point="before_petty_cash_usage")
			answer_callback_query(cqid, "Failed to save petty cash entry.", show_alert=True)
			edit_message_text(
				chat_id, message_id, f"Failed to save petty cash entry:\n<code>{e}</code>", parse_mode="HTML"
			)


def _get_categories():
	return frappe.get_all("Petty Cash Category", pluck="name", order_by="creation asc")


def _category_buttons(prefix, categories):
	return [[InlineKeyboardButton(cat, callback_data=f"{prefix}:cat:{cat}")] for cat in categories]
