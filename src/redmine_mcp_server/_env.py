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


def _is_tags_enabled() -> bool:
    """Check if AlphaNodes additional_tags plugin support is enabled."""
    return _is_true_env("REDMINE_TAGS_ENABLED", "false")


def _is_checklists_enabled() -> bool:
    """Check if RedmineUP Checklists plugin support is enabled."""
    return _is_true_env("REDMINE_CHECKLISTS_ENABLED", "false")


def _is_products_enabled() -> bool:
    """Check if RedmineUP Products plugin support is enabled."""
    return _is_true_env("REDMINE_PRODUCTS_ENABLED", "false")


def _is_crm_enabled() -> bool:
    """Check if RedmineUP CRM (Contacts) plugin support is enabled."""
    return _is_true_env("REDMINE_CRM_ENABLED", "false")


def _is_deals_enabled() -> bool:
    """Check if RedmineUP CRM *deals* support is enabled.

    Separate from :func:`_is_crm_enabled` even though deals ship inside the
    same plugin, because they are absent from the CRM plugin's Light
    edition: it declares no ``project_module :deals`` and therefore none of
    the ``*_deals`` permissions. Redmine builds its OAuth scope list from
    ``Redmine::AccessControl.permissions`` and applies
    ``enforce_configured_scopes``, so advertising a deal scope on a Light
    install is not merely useless -- the OAuth application cannot hold the
    scope, and a client requesting it fails consent with ``invalid_scope``,
    which would break contacts too. One flag per plugin would therefore
    regress a working Light deployment on upgrade.
    """
    return _is_true_env("REDMINE_DEALS_ENABLED", "false")


def _crm_edition() -> str:
    """Which build of the RedmineUP CRM plugin this Redmine runs.

    ``light`` (the default) or ``pro``. The plugin ships two builds whose
    ``ContactQuery`` differs: the Pro build registers 22 contact query filters,
    the Light build registers ``tags`` and nothing else. Redmine drops an
    unregistered filter parameter without complaining --
    ``Query#build_from_params`` only walks ``available_filters``, and
    ``add_short_filter`` returns early on anything outside it -- so forwarding a
    filter the build does not register answers ``200`` with the whole
    collection, which a caller cannot tell from a filter that matched
    everything.

    The build cannot be detected: Redmine exposes plugin versions only through
    ``admin/plugins``, which is HTML and admin-only. Hence a setting, and it
    defaults to the build that registers less, so an unconfigured deployment
    refuses a filter it may not be able to apply rather than answering wrongly.
    """
    value = os.getenv("REDMINE_CRM_EDITION", "light").strip().lower()
    if value not in {"light", "pro"}:
        raise RuntimeError(
            f"REDMINE_CRM_EDITION must be 'light' or 'pro', got '{value}'."
        )
    return value


def _is_dmsf_enabled() -> bool:
    """Check if DMSF (document management) plugin support is enabled."""
    return _is_true_env("REDMINE_DMSF_ENABLED", "false")


def _is_scope_enforcement_enabled() -> bool:
    """Check if per-tool OAuth scope enforcement is enabled (#185).

    Default on. Set REDMINE_OAUTH_SCOPE_ENFORCEMENT=off to restore the
    pre-enforcement behavior (any active token can call any tool) while
    users re-consent tokens with the required scopes.
    """
    return _is_true_env("REDMINE_OAUTH_SCOPE_ENFORCEMENT", "true")


def _oauth_discovery_as() -> str:
    """Select the OAuth discovery profile (#188).

    ``redmine`` (default): advertise Redmine as the authorization server
    (issuer = REDMINE_URL), the post-#140 behavior. ``self``: advertise this
    MCP server as the authorization server (issuer = REDMINE_MCP_BASE_URL)
    while authorize/token stay on Redmine /oauth/*, for clients that probe the
    authorization server's canonical well-known location (e.g. Cursor).
    """
    value = os.getenv("REDMINE_OAUTH_DISCOVERY_AS", "redmine").strip().lower()
    if value not in {"redmine", "self"}:
        raise RuntimeError(
            "REDMINE_OAUTH_DISCOVERY_AS must be 'redmine' or 'self', " f"got '{value}'."
        )
    return value


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


def get_allowed_tools() -> set[str] | None:
    """Tool names an operator allow-lists, or ``None`` when unrestricted.

    Reads ``REDMINE_MCP_ALLOW_TOOLS`` (comma-separated). When that is unset,
    falls back to ``REDMINE_MCP_ALLOW_TOOLS_FILE`` (one name per line, ``#``
    starts a comment) -- the same env-var-wins-over-file precedence as
    :func:`get_secret`.

    Returns ``None`` when neither is set, so callers can distinguish "no
    allow list configured" from "configured but empty". A configured but
    empty list comes back as an empty set for the caller to reject.
    """
    raw = os.getenv("REDMINE_MCP_ALLOW_TOOLS")
    if raw is None:
        file_name = os.getenv("REDMINE_MCP_ALLOW_TOOLS_FILE")
        if not file_name:
            return None
        try:
            raw_lines = Path(file_name).read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise RuntimeError(
                "Could not read tool allow list from "
                f"REDMINE_MCP_ALLOW_TOOLS_FILE ({file_name}): {exc}"
            ) from exc
        entries = [line.split("#", 1)[0] for line in raw_lines]
    else:
        entries = raw.split(",")
    return {entry.strip() for entry in entries if entry.strip()}


def _get_int_env(var_name: str, default: int) -> int:
    """Parse an integer environment variable, falling back to default."""
    try:
        return int(os.getenv(var_name, str(default)))
    except (ValueError, TypeError):
        return default


def get_redmine_timeout() -> tuple[float, float] | None:
    """Return the ``(connect, read)`` timeout for Redmine HTTP calls.

    ``REDMINE_TIMEOUT`` is a single seconds value (default 30). It is applied
    as a connect timeout of at most 10s plus a read timeout of the full value,
    which is the shape ``requests`` expects.

    Returns ``None`` when set to 0 or less, which restores the pre-#214
    behavior of waiting forever. That escape hatch exists for genuinely slow
    Redmine instances; it also reintroduces the hang, so it is not a default.

    Two properties of the requests timeout are worth knowing when tuning it:
    the read timeout is the gap between bytes, not a cap on total transfer
    time, so it does not limit large attachment downloads; and the connect
    timeout applies per IP address, so an unresponsive dual-stack host can
    take twice the connect budget before failing.
    """
    seconds = _get_int_env("REDMINE_TIMEOUT", 30)
    if seconds <= 0:
        return None
    return (min(10.0, float(seconds)), float(seconds))


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
