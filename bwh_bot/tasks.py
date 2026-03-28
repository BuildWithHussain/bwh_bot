import frappe
from frappe.utils import add_months, get_first_day, get_last_day, today


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
	frappe.db.commit()
