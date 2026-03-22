import datetime

import frappe
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def from_date_buttons(prefix, include_today=False):
	today = frappe.utils.today()
	tomorrow = frappe.utils.add_days(today, 1)
	day_after = frappe.utils.add_days(today, 2)

	today_dt = datetime.date.fromisoformat(today)
	days_until_monday = (7 - today_dt.weekday()) % 7
	if days_until_monday == 0:
		days_until_monday = 7
	next_monday = frappe.utils.add_days(today, days_until_monday)

	buttons = []
	if include_today:
		buttons.append([
			InlineKeyboardButton(f"Today ({today})", callback_data=f"{prefix}:from:{today}"),
			InlineKeyboardButton(f"Tomorrow ({tomorrow})", callback_data=f"{prefix}:from:{tomorrow}"),
		])
		buttons.append([
			InlineKeyboardButton(f"Day After ({day_after})", callback_data=f"{prefix}:from:{day_after}"),
			InlineKeyboardButton(f"Next Monday ({next_monday})", callback_data=f"{prefix}:from:{next_monday}"),
		])
	else:
		buttons.append([
			InlineKeyboardButton(f"Tomorrow ({tomorrow})", callback_data=f"{prefix}:from:{tomorrow}"),
			InlineKeyboardButton(f"Day After ({day_after})", callback_data=f"{prefix}:from:{day_after}"),
		])
		buttons.append([
			InlineKeyboardButton(f"Next Monday ({next_monday})", callback_data=f"{prefix}:from:{next_monday}"),
		])

	buttons.append([InlineKeyboardButton("Custom date...", callback_data=f"{prefix}:custom_from")])
	return buttons


def to_date_buttons(prefix, from_date):
	same_day = from_date
	plus_one = frappe.utils.add_days(from_date, 1)
	plus_two = frappe.utils.add_days(from_date, 2)
	plus_four = frappe.utils.add_days(from_date, 4)

	return [
		[
			InlineKeyboardButton(f"Same day ({same_day})", callback_data=f"{prefix}:to:{same_day}"),
			InlineKeyboardButton(f"+1 day ({plus_one})", callback_data=f"{prefix}:to:{plus_one}"),
		],
		[
			InlineKeyboardButton(f"+2 days ({plus_two})", callback_data=f"{prefix}:to:{plus_two}"),
			InlineKeyboardButton(f"+4 days ({plus_four})", callback_data=f"{prefix}:to:{plus_four}"),
		],
		[InlineKeyboardButton("Custom date...", callback_data=f"{prefix}:custom_to")],
	]


def nav_buttons(prefix, show_back=True):
	buttons = []
	if show_back:
		buttons.append(InlineKeyboardButton("← Go Back", callback_data=f"{prefix}:back"))
	buttons.append(InlineKeyboardButton("Cancel", callback_data=f"{prefix}:cancel"))
	return [buttons]


def confirm_buttons(prefix, label="Confirm"):
	return [
		[InlineKeyboardButton(label, callback_data=f"{prefix}:confirm")],
	] + nav_buttons(prefix)


def make_keyboard(*button_rows):
	"""Flatten a list of button row lists into an InlineKeyboardMarkup."""
	rows = []
	for item in button_rows:
		if isinstance(item, list) and item and isinstance(item[0], list):
			rows.extend(item)
		else:
			rows.append(item)
	return InlineKeyboardMarkup(rows)
