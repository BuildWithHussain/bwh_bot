import frappe
from frappe.utils import add_months, get_first_day, get_last_day, today

from bwh_bot.telegram_utils import broadcast_to_whitelisted_chats


def _format_date_range(from_date, to_date):
	from_str = frappe.utils.formatdate(from_date, "d MMM")
	if str(from_date) == str(to_date):
		return from_str
	return f"{from_str} → {frappe.utils.formatdate(to_date, 'd MMM')}"


def send_daily_leave_notification():
	"""Daily cron: notify whitelisted chats about employees on approved leave today."""
	current_day = today()
	leaves = frappe.get_all(
		"Leave Application",
		filters={
			"docstatus": 1,
			"status": "Approved",
			"from_date": ["<=", current_day],
			"to_date": [">=", current_day],
		},
		fields=["employee_name", "leave_type", "from_date", "to_date", "half_day"],
		order_by="employee_name asc",
	)

	if not leaves:
		return

	lines = []
	for leave in leaves:
		date_range = _format_date_range(leave.from_date, leave.to_date)
		half_day_text = " · Half Day" if leave.half_day else ""
		lines.append(f"• <b>{leave.employee_name}</b> — {leave.leave_type} ({date_range}){half_day_text}")

	message = "🌴 <b>On Leave Today</b>\n\n" + "\n".join(lines)
	broadcast_to_whitelisted_chats(message)


def send_daily_wfh_notification():
	"""Daily cron: notify whitelisted chats about employees working from home today."""
	current_day = today()
	requests = frappe.get_all(
		"Attendance Request",
		filters={
			"docstatus": 1,
			"reason": "Work From Home",
			"from_date": ["<=", current_day],
			"to_date": [">=", current_day],
		},
		fields=["employee_name", "from_date", "to_date", "custom_total_wfh_days"],
		order_by="employee_name asc",
	)

	if not requests:
		return

	lines = []
	for req in requests:
		date_range = _format_date_range(req.from_date, req.to_date)
		half_day_text = " · Half Day" if req.custom_total_wfh_days == 0.5 else ""
		lines.append(f"• <b>{req.employee_name}</b> ({date_range}){half_day_text}")

	message = "🏠 <b>Working From Home Today</b>\n\n" + "\n".join(lines)
	broadcast_to_whitelisted_chats(message)


def create_monthly_petty_cash_journal_entry():
	"""Monthly cron: aggregate previous month's petty cash usage into a draft Journal Entry."""
	settings = frappe.get_single("BWH Bot Settings")
	cash_account = settings.default_cash_account
	company = settings.default_company

	if not cash_account or not company:
		frappe.log_error(
			"BWH Bot Settings missing default_cash_account or default_company. "
			"Cannot create petty cash journal entry.",
			"Petty Cash Journal Entry",
		)
		return

	prev_month = add_months(today(), -1)
	from_date = get_first_day(prev_month)
	to_date = get_last_day(prev_month)

	month_label = frappe.utils.formatdate(from_date, "MMMM yyyy")

	# Aggregate draft Petty Cash Usage records by category
	usage_data = frappe.get_all(
		"Petty Cash Usage",
		filters={
			"docstatus": 0,
			"expense_date": ["between", [from_date, to_date]],
		},
		fields=["category", "sum(amount) as total"],
		group_by="category",
	)

	if not usage_data:
		return

	# Build journal entry rows
	accounts = []
	grand_total = 0

	for row in usage_data:
		category_account = frappe.db.get_value("Petty Cash Category", row.category, "account")
		if not category_account:
			frappe.log_error(
				f"Petty Cash Category '{row.category}' has no linked account. Skipping.",
				"Petty Cash Journal Entry",
			)
			continue

		accounts.append({
			"account": category_account,
			"debit_in_account_currency": row.total,
			"credit_in_account_currency": 0,
		})
		grand_total += row.total

	if not accounts:
		return

	# Credit side: Cash In Hand
	accounts.append({
		"account": cash_account,
		"debit_in_account_currency": 0,
		"credit_in_account_currency": grand_total,
	})

	jv = frappe.get_doc({
		"doctype": "Journal Entry",
		"posting_date": to_date,
		"company": company,
		"voucher_type": "Journal Entry",
		"user_remark": f"Petty Cash Summary for {month_label}",
		"accounts": accounts,
	})
	jv.insert()
