from __future__ import annotations

"""Central role permission rules for BeeLine UI actions."""

TECHNICIAN_OR_ADMIN_ROLES = frozenset({"technician", "admin"})
ADMIN_ROLE = "admin"


def can_create_issue(role: str | None) -> bool:
    """Issue creation is intentionally available to every app user."""
    return True


def can_edit_issue(role: str | None) -> bool:
    return role in TECHNICIAN_OR_ADMIN_ROLES


def can_resolve_issue(role: str | None) -> bool:
    return role in TECHNICIAN_OR_ADMIN_ROLES


def can_close_issue(role: str | None) -> bool:
    return can_resolve_issue(role)


def can_archive_issue(role: str | None) -> bool:
    return role == ADMIN_ROLE


def can_delete_issue(role: str | None) -> bool:
    return role == ADMIN_ROLE


def can_dismiss_predictive_alert(role: str | None) -> bool:
    return role == ADMIN_ROLE


def can_manage_machine_intelligence(role: str | None) -> bool:
    return role == ADMIN_ROLE


def can_open_predictive_maintenance(role: str | None) -> bool:
    return role == ADMIN_ROLE


def can_open_settings(role: str | None) -> bool:
    return role == ADMIN_ROLE


def can_open_special(role: str | None) -> bool:
    return role == ADMIN_ROLE


def can_manage_users(role: str | None) -> bool:
    return role == ADMIN_ROLE


def can_use_database_tools(role: str | None) -> bool:
    return role == ADMIN_ROLE
