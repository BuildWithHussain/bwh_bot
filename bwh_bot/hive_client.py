"""Thin REST client for a remote Frappe site running Hive.

The bot lives on the HR site, which has no Hive doctypes of its own, so every
read and write goes over the remote site's API. Sites and their credentials are
configured in the Hive Sites table on BWH Bot Settings.
"""

import frappe
import requests
from frappe.utils.password import get_decrypted_password

# Remote calls happen inside a Telegram webhook request, so they must fail fast
# rather than hold the worker open waiting on an unreachable site.
TIMEOUT = 10

# Cap the pickers so a long list does not build an unwieldy inline keyboard.
MAX_PROJECTS = 30
MAX_MEMBERS = 30


class HiveSiteError(frappe.ValidationError):
	"""A remote Hive site rejected a request or could not be reached."""


def active_sites():
	"""Configured Hive sites that are enabled, in table order."""
	settings = frappe.get_single("BWH Bot Settings")
	return [row for row in settings.hive_sites if row.is_active]


def site_label(site):
	return site.label or _host(site.site_url)


def list_projects(site):
	"""Open, non-archived projects on the remote site, newest first."""
	return _get(
		site,
		"Hive Project",
		filters=[["is_archived", "=", 0], ["status", "=", "Open"]],
		fields=["name", "title"],
		order_by="modified desc",
		limit=MAX_PROJECTS,
	)


def list_members(site):
	"""Active team members on the remote site, who can be assigned work."""
	return _get(
		site,
		"Hive Member",
		filters=[["is_active", "=", 1], ["type", "=", "Team"]],
		fields=["user", "member_name"],
		order_by="member_name asc",
		limit=MAX_MEMBERS,
	)


def create_task(site, title, project, status, start_date, due_date, description=None):
	"""Insert a Hive Task on the remote site and return its name."""
	payload = {
		"title": title,
		"project": project,
		"status": status,
		"start_date": start_date,
		"due_date": due_date,
	}
	if description:
		payload["description"] = description

	response = _request(site, "POST", "/api/resource/Hive Task", json=payload)
	name = (response.get("data") or {}).get("name")
	if not name:
		raise HiveSiteError(f"{site_label(site)} did not return a task name")
	return name


def assign_task(site, task_name, users):
	"""Assign the remote task via the standard assignment API, which is how Hive
	tracks assignees (they live in `_assign`, not a child table)."""
	_request(
		site,
		"POST",
		"/api/method/frappe.desk.form.assign_to.add",
		json={
			"doctype": "Hive Task",
			"name": task_name,
			"assign_to": users,
			"notify": 0,
		},
	)


def task_url(site, task_name):
	return f"{_base(site.site_url)}/app/hive-task/{task_name}"


def _get(site, doctype, filters, fields, order_by, limit):
	response = _request(
		site,
		"GET",
		f"/api/resource/{doctype}",
		params={
			"filters": frappe.as_json(filters),
			"fields": frappe.as_json(fields),
			"order_by": order_by,
			"limit_page_length": limit,
		},
	)
	return response.get("data") or []


def _request(site, method, path, **kwargs):
	url = f"{_base(site.site_url)}{path}"
	try:
		response = requests.request(
			method,
			url,
			headers={"Authorization": _auth_header(site), "Accept": "application/json"},
			timeout=TIMEOUT,
			**kwargs,
		)
	except requests.RequestException as e:
		raise HiveSiteError(f"Could not reach {site_label(site)}: {e}") from e

	if response.status_code >= 400:
		raise HiveSiteError(f"{site_label(site)} returned {response.status_code}: {_error_text(response)}")

	try:
		return response.json()
	except ValueError as e:
		raise HiveSiteError(f"{site_label(site)} returned a non-JSON response") from e


def _auth_header(site):
	secret = get_decrypted_password("BWH Bot Hive Site", site.name, "api_secret", raise_exception=False)
	if not secret:
		raise HiveSiteError(f"{site_label(site)} has no API secret configured")
	return f"token {site.api_key}:{secret}"


def _error_text(response):
	"""Pull the useful line out of a Frappe error response, without the traceback."""
	try:
		payload = response.json()
	except ValueError:
		return (response.text or "").strip()[:200]

	for key in ("exception", "message", "exc_type", "_server_messages"):
		if value := payload.get(key):
			return str(value)[:200]
	return str(payload)[:200]


def _base(site_url):
	return (site_url or "").rstrip("/")


def _host(site_url):
	return _base(site_url).split("://")[-1]
