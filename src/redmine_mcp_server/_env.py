"""Environment-variable accessor helpers."""

import os


def _is_true_env(var_name: str, default: str = "false") -> bool:
    """Parse common truthy env-var values."""
    return os.getenv(var_name, default).strip().lower() in {"1", "true", "yes", "on"}


def _is_read_only_mode() -> bool:
    """Check if the server is in read-only mode."""
    return _is_true_env("REDMINE_MCP_READ_ONLY", "false")


def _is_agile_enabled() -> bool:
    """Check if RedmineUP Agile plugin support is enabled."""
    return _is_true_env("REDMINE_AGILE_ENABLED", "false")


def _is_checklists_enabled() -> bool:
    """Check if RedmineUP Checklists plugin support is enabled."""
    return _is_true_env("REDMINE_CHECKLISTS_ENABLED", "false")


def _is_products_enabled() -> bool:
    """Check if RedmineUP Products plugin support is enabled."""
    return _is_true_env("REDMINE_PRODUCTS_ENABLED", "false")


def _is_crm_enabled() -> bool:
    """Check if RedmineUP CRM (Contacts) plugin support is enabled."""
    return _is_true_env("REDMINE_CRM_ENABLED", "false")


def _is_dmsf_enabled() -> bool:
    """Check if DMSF (document management) plugin support is enabled."""
    return _is_true_env("REDMINE_DMSF_ENABLED", "false")


def _admin_tools_enabled() -> bool:
    """Check if operator-facing admin tools are exposed on the MCP surface.

    Default ``False``. When unset, admin/cron-style tools
    (``cleanup_attachment_files`` and any future maintenance helpers)
    are not registered at import time and do not appear in
    ``tools/list``. Operators who want to drive cleanup through the
    MCP surface set ``REDMINE_MCP_EXPOSE_ADMIN_TOOLS=true`` to opt in;
    the underlying background cleanup task runs regardless of this flag.
    """
    return _is_true_env("REDMINE_MCP_EXPOSE_ADMIN_TOOLS", "false")


def _get_int_env(var_name: str, default: int) -> int:
    """Parse an integer environment variable, falling back to default."""
    try:
        return int(os.getenv(var_name, str(default)))
    except (ValueError, TypeError):
        return default


def get_introspection_credentials() -> tuple[str | None, str | None]:
    """Return (client_id, client_secret) for the Doorkeeper introspection client.

    Both values are required when REDMINE_AUTH_MODE=oauth. Returns
    (None, None) if neither is set. Callers that need fail-fast behaviour
    should use require_introspection_credentials().
    """
    client_id = os.getenv("REDMINE_INTROSPECT_CLIENT_ID") or None
    client_secret = os.getenv("REDMINE_INTROSPECT_CLIENT_SECRET") or None
    return client_id, client_secret


def require_introspection_credentials() -> tuple[str, str]:
    """Return (client_id, client_secret) or raise RuntimeError with a clear message.

    Used at OAuth-mode startup so the server fails fast instead of returning
    401 on every request.
    """
    client_id, client_secret = get_introspection_credentials()
    missing = []
    if not client_id:
        missing.append("REDMINE_INTROSPECT_CLIENT_ID")
    if not client_secret:
        missing.append("REDMINE_INTROSPECT_CLIENT_SECRET")
    if missing:
        raise RuntimeError(
            "OAuth mode requires Doorkeeper introspection credentials. "
            f"Missing env var(s): {', '.join(missing)}. "
            "Register a confidential OAuth client in Redmine with "
            "protected_resource? permission and set these vars. "
            "See docs/oauth-setup.md."
        )
    return client_id, client_secret


def get_health_introspection_ttl_seconds() -> int:
    """How long /health caches the Doorkeeper introspection probe result."""
    return _get_int_env("HEALTH_INTROSPECTION_TTL_SECONDS", 30)
