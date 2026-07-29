# Copyright (c) 2026, BWH and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class BWHBotHiveSite(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Data
		api_secret: DF.Password
		is_active: DF.Check
		label: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		site_url: DF.Data
	# end: auto-generated types

	_DOCTYPE_NAME = "BWH Bot Hive Site"
