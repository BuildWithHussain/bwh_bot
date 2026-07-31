import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"Attendance Request": [
		{
			"fieldname": "custom_total_wfh_days",
			"label": "Total WFH Days",
			"fieldtype": "Float",
			"precision": "1",
			"insert_after": "half_day_date",
			"description": (
				"Total Work From Home days captured by BWH Bot. "
				"For a half day this is 0.5; for a multi-day request it is the number of days. "
				"This is used instead of the Half Day checkbox so WFH is not split into "
				"half present / half absent in attendance."
			),
		}
	],
}


def after_install():
	_make_custom_fields()


def after_migrate():
	_make_custom_fields()


def _make_custom_fields():
	fields = {
		doctype: definitions
		for doctype, definitions in CUSTOM_FIELDS.items()
		if frappe.db.exists("DocType", doctype)
	}
	if fields:
		create_custom_fields(fields, ignore_validate=True)
