"""Environment-variable accessor helpers."""

import os
from pathlib import Path


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


def _get_upload_file_roots() -> list[str]:
    """Return realpath-resolved directory roots allowed as ``file_path`` upload
    sources.

    Always includes ``realpath(ATTACHMENTS_DIR)`` (default ``./attachments``),
    where downloaded attachments are written. Additional roots come from
    ``REDMINE_MCP_UPLOAD_FILE_ROOTS`` (``os.pathsep``-separated). Blank entries
    are skipped and duplicates are removed while preserving order.
    """
    roots: list[str] = []

    def _add(path: str) -> None:
        resolved = os.path.realpath(path)
        if resolved not in roots:
            roots.append(resolved)

    _add(os.getenv("ATTACHMENTS_DIR", "./attachments"))
    raw = os.getenv("REDMINE_MCP_UPLOAD_FILE_ROOTS", "")
    for entry in raw.split(os.pathsep):
        entry = entry.strip()
        if entry:
            _add(entry)
    return roots


def get_secret(var_name: str) -> str | None:
    """Return a secret from an env var or Docker/Kubernetes-style file env var."""
    value = os.getenv(var_name)
    if value:
        return value

    file_name = os.getenv(f"{var_name}_FILE")
    if not file_name:
        return None

    try:
        return Path(file_name).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(
            f"Could not read secret file for {var_name}_FILE " f"({file_name}): {exc}"
        ) from exc


def get_required(
    var_name: str,
    *,
    error_text: str | None = None,
) -> str:
    """Return a required environment variable or raise a clear RuntimeError."""
    value = os.getenv(var_name)
    if value:
        return value

    message = f"Missing required env var: {var_name}."
    if error_text:
        message = f"{message} {error_text}"
    raise RuntimeError(message)


def get_required_secret(
    var_name: str,
    *,
    error_text: str | None = None,
) -> str:
    """Return a required secret from env or a file env var."""
    value = get_secret(var_name)
    if value:
        return value

    message = f"Missing required secret env var: {var_name} or {var_name}_FILE."
    if error_text:
        message = f"{message} {error_text}"
    raise RuntimeError(message)


def get_introspection_credentials() -> tuple[str | None, str | None]:
    """Return (client_id, client_secret) for the Doorkeeper introspection client.

    Both values are required when REDMINE_AUTH_MODE=oauth. Returns
    (None, None) if neither is set. Callers that need fail-fast behaviour
    should use require_introspection_credentials().
    """
    return (
        os.getenv("REDMINE_INTROSPECT_CLIENT_ID") or None,
        get_secret("REDMINE_INTROSPECT_CLIENT_SECRET"),
    )


def require_introspection_credentials() -> tuple[str, str]:
    """Return (client_id, client_secret) or raise RuntimeError with a clear message.

    Used at OAuth-mode startup so the server fails fast instead of returning
    401 on every request.
    """
    error_text = (
        "OAuth mode requires Doorkeeper introspection credentials. "
        "Register a confidential OAuth client in Redmine and configure "
        "Doorkeeper's allow_token_introspection block to accept it "
        "(see docs/oauth-setup.md Step 2 for the walkthrough)."
    )
    return (
        get_required("REDMINE_INTROSPECT_CLIENT_ID", error_text=error_text),
        get_required_secret("REDMINE_INTROSPECT_CLIENT_SECRET", error_text=error_text),
    )


def get_health_introspection_ttl_seconds() -> int:
    """How long /health caches the Doorkeeper introspection probe result."""
    return _get_int_env("HEALTH_INTROSPECTION_TTL_SECONDS", 30)


def get_allowed_client_redirect_uris() -> list[str] | None:
    """Allowed client redirect-URI patterns for oauth-proxy mode.

    Controls which redirect URIs an MCP client may register and use via
    ``REDMINE_MCP_ALLOWED_CLIENT_REDIRECT_URIS``:

    - Unset: loopback-only default (``http://localhost:*`` and
      ``http://127.0.0.1:*``), which covers the common local-client case
      while blocking remote redirect targets.
    - A literal ``*``: returns ``None``, which tells FastMCP's ``OAuthProxy``
      to accept any redirect URI (the DCR-permissive default). Use only when
      hosted clients with non-loopback redirect URIs are required.
    - Otherwise: a comma- or space-separated list of glob patterns, e.g.
      ``https://app.example.com/*``.

    A blank value falls back to the loopback default rather than accepting
    none, since an empty allowlist would reject every client.
    """
    loopback = ["http://localhost:*", "http://127.0.0.1:*"]
    raw = os.getenv("REDMINE_MCP_ALLOWED_CLIENT_REDIRECT_URIS")
    if raw is None:
        return loopback
    if raw.strip() == "*":
        return None
    patterns = [p for p in raw.replace(",", " ").split() if p]
    return patterns or loopback
