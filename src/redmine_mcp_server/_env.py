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


def _get_int_env(var_name: str, default: int) -> int:
    """Parse an integer environment variable, falling back to default."""
    try:
        return int(os.getenv(var_name, str(default)))
    except (ValueError, TypeError):
        return default
