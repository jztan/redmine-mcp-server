"""Who is calling, as far as a staged upload needs to know.

A staged upload is bound to the caller that reserved it (see
``_upload_store``), so the server has to name that caller twice: when the
ticket is created, and again when an ``upload_id`` is read back. What it can
name depends on the auth mode. The answers carry a prefix that keeps a
digest of an API key apart from a Redmine user id, so the two can never be
taken for one another; a ``sub`` and a looked-up id share ``redmine-user:``
on purpose, since both name the same Redmine user:

- ``api-key-login``: the Redmine user id the browser login bound to the
  token, ``redmine-user:<id>``.
- ``oauth`` and ``oauth-proxy``: the introspection response's ``sub``, as
  ``redmine-user:<sub>``, when the authorization server emits one. It has
  to be the Redmine user id (``docs/oauth-setup.md`` says how), so that it
  matches what the lookup would find. Redmine's Doorkeeper emits none by
  default, and then the user is looked up with one
  ``GET /users/current.json`` (see :func:`resolve_staged_upload_owner`).
  The bearer itself is no identity: it changes on every refresh, and the
  OAuth ``client_id`` is the same for every user in oauth-proxy mode.
- ``legacy-per-user``: a SHA-256 digest of the caller's
  ``X-Redmine-API-Key``, ``api-key:<hex>``. The key itself is never stored.
  It is checked the way every tool call checks it first, so a slot is never
  bound to the digest of a header the call would then refuse.
- ``legacy``: everyone is the one configured account, so there is no one to
  tell apart and the answer is ``None``.

``None`` from either function means "nobody in particular". A bound slot
refuses it. Where a caller should have been identifiable and was not -- see
:func:`identity_expected` -- ``create_upload_ticket`` refuses the ticket
rather than reserve a slot anyone could read; only ``legacy`` mode, where
there is no one to tell apart, creates unbound slots.
"""

import logging
from typing import Optional

from fastmcp.server.dependencies import get_access_token, get_http_request

from ._offload import in_thread

logger = logging.getLogger("redmine_mcp_server")

_OAUTH_MODES = frozenset({"oauth", "oauth-proxy"})


def _auth_mode() -> str:
    """The configured auth mode, read through ``_client`` at call time.

    Imported here rather than at module level, the way ``_per_user`` reaches
    ``_client``: several test modules reload ``_client``, and a binding taken
    at import would keep reading the module they replaced.
    """
    from . import _client

    return _client.REDMINE_AUTH_MODE


def staged_upload_owner() -> Optional[str]:
    """The caller's identity, where it is known without asking Redmine.

    Safe on the event loop: it reads the verified token and the request
    headers and nothing else. In the OAuth modes it answers ``None`` when the
    token carries no ``sub``, and :func:`resolve_staged_upload_owner` is the
    one that goes on to ask Redmine.
    """
    mode = _auth_mode()

    if mode == "api-key-login":
        claims = getattr(get_access_token(), "claims", None)
        user_id = claims.get("redmine_user_id") if isinstance(claims, dict) else None
        if user_id in (None, ""):
            return None
        return f"redmine-user:{user_id}"

    if mode in _OAUTH_MODES:
        subject = getattr(get_access_token(), "subject", None)
        return f"redmine-user:{subject}" if subject else None

    if mode == "legacy-per-user":
        from ._per_user import PerUserAuthError, _cache_key, resolve_per_user_key

        try:
            request = get_http_request()
        except RuntimeError:
            request = None
        # The same checks _get_redmine_client() applies -- transport, presence,
        # format -- so a header that call would refuse binds nothing either.
        try:
            key = resolve_per_user_key(request)
        except PerUserAuthError:
            return None
        return f"api-key:{_cache_key(key)}"

    return None


def identity_expected() -> bool:
    """Whether this request ought to have an identity to bind a slot to.

    True in ``api-key-login`` and ``legacy-per-user``, where every request
    carries its caller, and in the OAuth modes whenever there is a verified
    token. False in ``legacy``, and in the OAuth modes without a token, which
    is no authenticated request at all. Where this is true and no owner
    could be worked out, the ticket is refused: an unbound slot there would
    quietly hand the file to anyone who learns its id, which is the hole the
    binding exists to close.
    """
    mode = _auth_mode()
    if mode in ("api-key-login", "legacy-per-user"):
        return True
    if mode in _OAUTH_MODES:
        return get_access_token() is not None
    return False


_UNIDENTIFIED = "Could not identify the caller to bind this upload to."

# What to do about it, by mode. In the OAuth modes the usual cause is the
# /users/current.json lookup failing, which a retry often clears; in the other
# two the request itself is missing what names the caller, and a retry would
# carry the same gap.
_UNIDENTIFIED_REMEDY = {
    "api-key-login": (
        "The session is not bound to a Redmine user. Reconnect to sign in again."
    ),
    "legacy-per-user": (
        "Send your Redmine API key in the X-Redmine-API-Key header, over TLS."
    ),
}
_UNIDENTIFIED_OAUTH_REMEDY = (
    "Try again; if it persists, check that the token can read "
    "GET /users/current.json."
)


def unidentified_caller_error() -> dict:
    """The error ``create_upload_ticket`` answers when it cannot bind a slot.

    Worded for the configured mode, since what the caller can do about it
    differs: retry in the OAuth modes, sign in again or fix the header in
    the others.
    """
    remedy = _UNIDENTIFIED_REMEDY.get(_auth_mode(), _UNIDENTIFIED_OAUTH_REMEDY)
    return {"error": f"{_UNIDENTIFIED} {remedy}"}


def _current_redmine_user() -> Optional[str]:
    """Ask Redmine who the bearer belongs to. Blocking; worker threads only.

    Any failure answers ``None`` rather than raising. A bound slot then reads
    as unknown, and ``create_upload_ticket`` refuses the ticket instead of
    creating a slot it cannot bind; either way the tool call says so rather
    than failing with whatever the lookup raised. Not cached: the answer is
    cheap next to the upload it guards, and a cache keyed on the bearer would
    have to outlive refreshes to be any use.
    """
    if get_access_token() is None:
        # No authenticated request to identify. Without a token
        # _get_redmine_client() would fall back to the configured account,
        # and every unauthenticated caller would share its identity.
        return None
    from . import _client

    try:
        user = _client._get_redmine_client().user.get("current")
        user_id = getattr(user, "id", None)
    except Exception as exc:  # noqa: BLE001 - see docstring
        logger.debug(
            "Could not resolve the Redmine user for a staged upload (%s).",
            type(exc).__name__,
        )
        return None
    if user_id is None:
        return None
    return f"redmine-user:{user_id}"


def _needs_lookup(owner: Optional[str]) -> bool:
    """Whether only Redmine can name the caller, which is an OAuth mode
    that found no ``sub``.

    Checked on the calling side of the thread hop, so the modes that never
    ask Redmine never pay for one. A request with no token at all also lands
    here, and :func:`_current_redmine_user` declines it before asking.
    """
    return owner is None and _auth_mode() in _OAUTH_MODES


def resolve_staged_upload_owner_blocking() -> Optional[str]:
    """:func:`resolve_staged_upload_owner` for code already in a worker thread.

    A tool body under ``@offloaded`` runs off the event loop, where the
    Redmine lookup may block, and has no loop of its own to await on.
    """
    owner = staged_upload_owner()
    return _current_redmine_user() if _needs_lookup(owner) else owner


async def resolve_staged_upload_owner() -> Optional[str]:
    """The caller's identity, asking Redmine when nothing local says.

    Only the OAuth modes ever ask, and only when the token carries no
    ``sub``: then one ``GET /users/current.json`` with the caller's own
    bearer names the user. That runs in a worker thread, since the Redmine
    client blocks. Every other mode answers from what the request already
    carries.
    """
    owner = staged_upload_owner()
    return await in_thread(_current_redmine_user) if _needs_lookup(owner) else owner
