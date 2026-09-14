"""``api-key-login``: this server as its own OAuth authorization server.

The three older modes all fail on a Redmine without Doorkeeper. ``legacy``
shares one API key, so everyone is the same Redmine user. ``legacy-per-user``
needs an ``X-Redmine-API-Key`` header per request, which a centrally
distributed client cannot supply per user. ``oauth`` and ``oauth-proxy`` need
Doorkeeper's endpoints, which Easy Redmine does not mount and no Redmine below
6.1 has.

Here the server issues its own tokens. The browser step is a page this server
serves (see ``_api_key_login_routes``); the user pastes their personal Redmine
API key, the server validates it with one ``GET /users/current.json``, and
binds it to the tokens it mints. Every tool call then runs as that user, under
that user's Redmine permissions.

Store layout, one collection per record kind::

    clients          client_id          the DCR registration
    transactions     random id          a pending /authorize, TTL 5 min
    codes            random code        AuthorizationCode + binding_id
    bindings         random id          the API key and who it belongs to
    access_tokens    sha256(token)      {binding_id, scopes, expires_at}
    refresh_tokens   sha256(token)      {binding_id, scopes, expires_at}
    rotated_refresh  sha256(old token)  tombstone for reuse detection

Tokens are stored by hash, so a directory listing yields nothing usable. Every
write passes the record's remaining lifetime as the store TTL, so transactions,
codes and tokens expire on their own and no pruning job is needed.

Two properties are load-bearing and easy to break:

* **Revocation never enumerates.** Access and refresh tokens hold a
  ``binding_id`` and dereference it on load. Deleting the binding invalidates
  every token pointing at it, which matters because the store contract is
  ``get``/``put``/``delete``/``ttl`` only -- ``keys()`` is optional and not
  guaranteed through the encryption wrapper.
* **Single use rides on ``delete()``.** The store has no compare-and-swap, so
  a transaction, a code, or a rotated refresh token is claimed by deleting it
  and proceeding only when ``delete()`` returns ``True``. The one counter that
  cannot work this way, ``attempts``, is documented as approximate.
"""

import hashlib
import logging
import os
import secrets
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Mapping, Optional

import httpx
from fastmcp import settings
from fastmcp.server.auth import OAuthProvider
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from fastmcp.server.auth.redirect_validation import (
    build_client_redirect,
    validate_redirect_uri,
)
from cryptography.fernet import Fernet
from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from ._env import (
    _get_int_env,
    _is_true_env,
    get_allowed_client_redirect_uris,
    get_redmine_timeout,
    get_required,
    get_required_secret,
)
from .oauth_scopes import configured_advertised_scopes

logger = logging.getLogger(__name__)

STORE_SUBDIR = "api-key-login"

COLLECTION_CLIENTS = "clients"
COLLECTION_TRANSACTIONS = "transactions"
COLLECTION_CODES = "codes"
COLLECTION_BINDINGS = "bindings"
COLLECTION_ACCESS_TOKENS = "access_tokens"
COLLECTION_REFRESH_TOKENS = "refresh_tokens"
COLLECTION_ROTATED_REFRESH = "rotated_refresh"

DEFAULT_ACCESS_TOKEN_TTL = 3600
DEFAULT_SESSION_DAYS = 30
DEFAULT_TRANSACTION_TTL = 300
DEFAULT_CODE_TTL = 300
MAX_LOGIN_ATTEMPTS = 3

# Doorkeeper-issued tokens can carry ``admin``, which bypasses every per-tool
# scope check (see _scope_middleware). A self-issued token never gets it.
ADMIN_SCOPE = "admin"


class ApiKeyLoginError(Exception):
    """A login attempt failed for a reason the user should see."""

    def __init__(self, message: str, *, drop_transaction: bool = False):
        super().__init__(message)
        self.message = message
        # True when retrying this transaction cannot help (bad CSRF, admin key).
        self.drop_transaction = drop_transaction


def _token() -> str:
    return secrets.token_urlsafe(32)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> float:
    return time.time()


# --- binding protection ------------------------------------------------


class BindingProtection(ABC):
    """How a binding's payload is protected at rest.

    Two schemes are planned and only one ships today. They sit behind this
    interface so nothing in the provider branches on which is in use:
    ``seal`` produces the record written to ``bindings``, ``wrap`` produces the
    fields added to whichever secret may later open it (the authorization code,
    then each token minted from it), and ``unwrap``/``unseal`` reverse that.

    ``server-secret`` (this file) leans on the store's own
    ``FernetEncryptionWrapper`` and therefore needs no data key: ``wrap``
    returns nothing and ``unseal`` ignores the key argument. The token-derived
    scheme lands separately and fills those in without touching the provider.
    """

    @abstractmethod
    def seal(
        self, payload: Mapping[str, Any]
    ) -> tuple[dict[str, Any], Optional[bytes]]:
        """Return the record to store and the data key that opens it, if any."""

    @abstractmethod
    def wrap(self, data_key: Optional[bytes], secret: str) -> dict[str, Any]:
        """Return fields to merge into the record holding ``secret``."""

    @abstractmethod
    def unwrap(self, carrier: Mapping[str, Any], secret: str) -> Optional[bytes]:
        """Recover the data key from a code or token record."""

    @abstractmethod
    def unseal(
        self, record: Mapping[str, Any], data_key: Optional[bytes]
    ) -> Optional[dict[str, Any]]:
        """Return the binding payload, or ``None`` when it cannot be opened."""


class ServerSecretBindingProtection(BindingProtection):
    """The default: rely on the store's Fernet wrapper, hold no data key.

    Everything written through the store is already encrypted under a key
    derived from ``REDMINE_MCP_JWT_SIGNING_KEY``, so the payload needs no
    second layer. The cost is stated plainly in the docs: whoever holds the
    volume *and* the operator secret reads every binding.
    """

    def seal(
        self, payload: Mapping[str, Any]
    ) -> tuple[dict[str, Any], Optional[bytes]]:
        return dict(payload), None

    def wrap(self, data_key: Optional[bytes], secret: str) -> dict[str, Any]:
        return {}

    def unwrap(self, carrier: Mapping[str, Any], secret: str) -> Optional[bytes]:
        return None

    def unseal(
        self, record: Mapping[str, Any], data_key: Optional[bytes]
    ) -> Optional[dict[str, Any]]:
        return dict(record)


# --- Redmine identity --------------------------------------------------


async def fetch_redmine_identity(
    redmine_url: str, api_key: str, *, timeout: Any = None
) -> Optional[dict[str, Any]]:
    """Validate an API key against Redmine and return ``{id, login, admin}``.

    ``None`` means Redmine rejected the key (401/403). A transport failure
    propagates as ``httpx.RequestError`` so the caller can tell "your key is
    wrong" from "Redmine is down" -- the first costs the user an attempt, the
    second must not.

    The key travels in the ``X-Redmine-API-Key`` header, never in the query
    string, so it cannot land in Redmine's access log.
    """
    from ._client import httpx_ssl_kwargs

    url = f"{redmine_url.rstrip('/')}/users/current.json"
    request_timeout = timeout if timeout is not None else get_redmine_timeout()
    async with httpx.AsyncClient(
        timeout=request_timeout, **httpx_ssl_kwargs(url)
    ) as client:
        response = await client.get(url, headers={"X-Redmine-API-Key": api_key})
    if response.status_code in (401, 403):
        return None
    response.raise_for_status()
    user = response.json().get("user") or {}
    return {
        "id": user.get("id"),
        "login": user.get("login") or "",
        "admin": bool(user.get("admin")),
    }


# --- the provider ------------------------------------------------------


class ApiKeyLoginProvider(OAuthProvider):
    """An OAuth authorization server whose consent step collects an API key."""

    def __init__(
        self,
        *,
        base_url: str,
        redmine_url: str,
        store: AsyncKeyValue,
        scopes_supported: list[str],
        allowed_client_redirect_uris: Optional[list[str]],
        allow_admin: bool = False,
        access_token_ttl: int = DEFAULT_ACCESS_TOKEN_TTL,
        session_ttl: int = DEFAULT_SESSION_DAYS * 86400,
        transaction_ttl: int = DEFAULT_TRANSACTION_TTL,
        protection: Optional[BindingProtection] = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=list(scopes_supported),
                default_scopes=list(scopes_supported),
            ),
            revocation_options=RevocationOptions(enabled=True),
        )
        self._redmine_url = redmine_url.rstrip("/")
        self._store = store
        self._advertised = list(scopes_supported)
        self._allowed_client_redirect_uris = allowed_client_redirect_uris
        self._allow_admin = allow_admin
        self._access_token_ttl = access_token_ttl
        self._session_ttl = session_ttl
        self._transaction_ttl = transaction_ttl
        self._protection = protection or ServerSecretBindingProtection()

    # -- properties used by the routes -----------------------------------

    @property
    def redmine_url(self) -> str:
        return self._redmine_url

    @property
    def login_path(self) -> str:
        return "/login"

    # -- client registration ---------------------------------------------

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Reject a registration naming a redirect URI outside the allowlist.

        Registration is open, so this is the first of the two places the
        allowlist is applied; ``authorize`` exact-matches against what was
        registered. Without it a crafted authorize link could send the code
        anywhere.
        """
        for redirect_uri in client_info.redirect_uris or []:
            if not validate_redirect_uri(
                redirect_uri, self._allowed_client_redirect_uris
            ):
                raise ValueError(
                    f"redirect_uri {redirect_uri} is not allowed by this server. "
                    "Ask the operator to add it to "
                    "REDMINE_MCP_ALLOWED_CLIENT_REDIRECT_URIS."
                )
        await self._store.put(
            client_info.client_id,
            client_info.model_dump(mode="json"),
            collection=COLLECTION_CLIENTS,
            ttl=self._session_ttl,
        )

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        record = await self._store.get(client_id, collection=COLLECTION_CLIENTS)
        if record is None:
            return None
        return OAuthClientInformationFull.model_validate(record)

    # -- authorize --------------------------------------------------------

    def _granted_scopes(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> list[str]:
        """Narrow the client's request to what this deployment advertises.

        The SDK's registration handler already fills an absent scope with
        ``default_scopes`` and rejects anything outside ``valid_scopes``, so by
        here the request is a subset of the advertised set in the normal case.
        The intersection is kept anyway because ``authorize`` is reachable with
        a hand-built request.

        ``admin`` is dropped explicitly. It is not in ``advertised_scopes()``
        today, so the intersection already removes it -- this is a guard
        against a future change to that list, not dead code, because an
        ``admin`` scope would bypass every per-tool check.
        """
        requested = list(params.scopes or [])
        if not requested and client.scope:
            requested = client.scope.split()
        advertised = set(self._advertised)
        granted = [s for s in requested if s in advertised and s != ADMIN_SCOPE]
        return granted

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        registered = [str(uri) for uri in (client.redirect_uris or [])]
        if str(params.redirect_uri) not in registered:
            raise ValueError("redirect_uri does not match this client's registration.")

        txn_id = _token()
        transaction = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            # Must round-trip onto the AuthorizationCode: the SDK's token
            # handler compares it, and defaulting it to False makes every
            # client that echoes redirect_uri at /token (Claude Code and Cursor
            # among them) fail with "redirect_uri did not match".
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "code_challenge": params.code_challenge,
            "state": params.state,
            "resource": params.resource,
            "scopes": self._granted_scopes(client, params),
            "csrf": _token(),
            "browser_nonce": _token(),
            "attempts": 0,
            "expires_at": _now() + self._transaction_ttl,
        }
        await self._store.put(
            txn_id,
            transaction,
            collection=COLLECTION_TRANSACTIONS,
            ttl=self._transaction_ttl,
        )
        # Keep the registration alive for as long as sessions can last, so an
        # idle-but-valid client is not evicted mid-session.
        await self._refresh_client_ttl(client)
        return f"{str(self.base_url).rstrip('/')}{self.login_path}?txn={txn_id}"

    async def _refresh_client_ttl(self, client: OAuthClientInformationFull) -> None:
        await self._store.put(
            client.client_id,
            client.model_dump(mode="json"),
            collection=COLLECTION_CLIENTS,
            ttl=self._session_ttl,
        )

    # -- the login step ---------------------------------------------------

    async def get_transaction(self, txn_id: str) -> Optional[dict[str, Any]]:
        """Return a pending transaction, or ``None`` when unknown or expired."""
        record = await self._store.get(txn_id, collection=COLLECTION_TRANSACTIONS)
        if record is None:
            return None
        if float(record.get("expires_at", 0)) < _now():
            await self._store.delete(txn_id, collection=COLLECTION_TRANSACTIONS)
            return None
        return record

    async def drop_transaction(self, txn_id: str) -> None:
        await self._store.delete(txn_id, collection=COLLECTION_TRANSACTIONS)

    async def _count_attempt(self, txn_id: str, transaction: dict[str, Any]) -> None:
        """Charge one attempt, dropping the transaction once the budget is out.

        Read-modify-write on a store without compare-and-swap, so two
        concurrent POSTs can read the same value and the budget stretches. That
        is accepted: the budget bounds noise and log spam, not guessing --
        stock Redmine keys are 40 hex characters, so brute force is
        impractical regardless.
        """
        attempts = int(transaction.get("attempts", 0)) + 1
        if attempts >= MAX_LOGIN_ATTEMPTS:
            await self._store.delete(txn_id, collection=COLLECTION_TRANSACTIONS)
            return
        transaction["attempts"] = attempts
        remaining = max(1.0, float(transaction.get("expires_at", 0)) - _now())
        await self._store.put(
            txn_id,
            transaction,
            collection=COLLECTION_TRANSACTIONS,
            ttl=remaining,
        )

    async def complete_login(
        self,
        txn_id: str,
        csrf: str,
        api_key: str,
        *,
        browser_nonce: Optional[str] = None,
    ) -> str:
        """Validate the key, bind it, and return the client redirect URL.

        Raises :class:`ApiKeyLoginError` for anything the user should see. A
        transport failure reaching Redmine propagates unchanged so the route
        can answer 502 and keep the transaction: the user's key may be fine.
        """
        transaction = await self.get_transaction(txn_id)
        if transaction is None:
            raise ApiKeyLoginError(
                "This login page has expired or was already used. "
                "Start the connection again in your client."
            )
        if not secrets.compare_digest(str(transaction.get("csrf", "")), csrf or ""):
            await self.drop_transaction(txn_id)
            raise ApiKeyLoginError(
                "This form is no longer valid.", drop_transaction=True
            )
        if browser_nonce is not None and not secrets.compare_digest(
            str(transaction.get("browser_nonce", "")), browser_nonce
        ):
            await self.drop_transaction(txn_id)
            raise ApiKeyLoginError(
                "This login page was opened in a different browser.",
                drop_transaction=True,
            )

        identity = await fetch_redmine_identity(self._redmine_url, api_key)
        if identity is None:
            await self._count_attempt(txn_id, transaction)
            raise ApiKeyLoginError("Redmine rejected this API key.")
        if identity["admin"] and not self._allow_admin:
            await self.drop_transaction(txn_id)
            raise ApiKeyLoginError(
                "Keys of Redmine administrators are not accepted here.",
                drop_transaction=True,
            )

        # Claim the transaction. The store has no compare-and-swap, so the
        # delete result is what makes a double submit fail on the second.
        claimed = await self._store.delete(txn_id, collection=COLLECTION_TRANSACTIONS)
        if not claimed:
            raise ApiKeyLoginError("This login was already completed.")

        binding_id, data_key = await self._create_binding(
            transaction, api_key, identity
        )
        code = await self._mint_code(transaction, binding_id, identity, data_key)
        params = {"code": code}
        if transaction.get("state"):
            params["state"] = str(transaction["state"])
        return build_client_redirect(
            str(transaction["redirect_uri"]),
            params,
            iss=str(self.base_url).rstrip("/"),
        )

    async def _create_binding(
        self,
        transaction: Mapping[str, Any],
        api_key: str,
        identity: Mapping[str, Any],
    ) -> tuple[str, Optional[bytes]]:
        binding_id = _token()
        payload = {
            "api_key": api_key,
            "redmine_user_id": identity["id"],
            "redmine_login": identity["login"],
            "client_id": transaction["client_id"],
            "scopes": list(transaction.get("scopes", [])),
            "created_at": _now(),
            "session_expires_at": _now() + self._session_ttl,
        }
        record, data_key = self._protection.seal(payload)
        record["session_expires_at"] = payload["session_expires_at"]
        await self._store.put(
            binding_id,
            record,
            collection=COLLECTION_BINDINGS,
            ttl=self._session_ttl,
        )
        return binding_id, data_key

    async def _mint_code(
        self,
        transaction: Mapping[str, Any],
        binding_id: str,
        identity: Mapping[str, Any],
        data_key: Optional[bytes],
    ) -> str:
        code = _token()
        record = {
            "code": code,
            "client_id": transaction["client_id"],
            "redirect_uri": str(transaction["redirect_uri"]),
            "redirect_uri_provided_explicitly": bool(
                transaction.get("redirect_uri_provided_explicitly")
            ),
            "code_challenge": transaction.get("code_challenge"),
            "scopes": list(transaction.get("scopes", [])),
            "resource": transaction.get("resource"),
            "subject": str(identity["id"]),
            "expires_at": _now() + DEFAULT_CODE_TTL,
            "binding_id": binding_id,
        }
        record.update(self._protection.wrap(data_key, code))
        await self._store.put(
            code, record, collection=COLLECTION_CODES, ttl=DEFAULT_CODE_TTL
        )
        return code

    # -- code and token exchange ------------------------------------------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[AuthorizationCode]:
        record = await self._store.get(authorization_code, collection=COLLECTION_CODES)
        if record is None or record.get("client_id") != client.client_id:
            return None
        if float(record.get("expires_at", 0)) < _now():
            await self._store.delete(authorization_code, collection=COLLECTION_CODES)
            return None
        return AuthorizationCode(
            code=record["code"],
            scopes=list(record.get("scopes", [])),
            expires_at=float(record["expires_at"]),
            client_id=record["client_id"],
            code_challenge=record.get("code_challenge") or "",
            redirect_uri=record["redirect_uri"],
            redirect_uri_provided_explicitly=bool(
                record.get("redirect_uri_provided_explicitly")
            ),
            resource=record.get("resource"),
            subject=record.get("subject"),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        record = await self._store.get(
            authorization_code.code, collection=COLLECTION_CODES
        )
        claimed = await self._store.delete(
            authorization_code.code, collection=COLLECTION_CODES
        )
        if record is None or not claimed:
            raise ValueError("Authorization code is not valid.")

        binding_id = str(record["binding_id"])
        data_key = self._protection.unwrap(record, authorization_code.code)
        return await self._issue_pair(
            binding_id=binding_id,
            client_id=client.client_id,
            scopes=list(authorization_code.scopes),
            data_key=data_key,
            subject=record.get("subject"),
        )

    async def _issue_pair(
        self,
        *,
        binding_id: str,
        client_id: str,
        scopes: list[str],
        data_key: Optional[bytes],
        subject: Optional[str],
        session_expires_at: Optional[float] = None,
    ) -> OAuthToken:
        binding = await self._store.get(binding_id, collection=COLLECTION_BINDINGS)
        if binding is None:
            raise ValueError("This session has been revoked.")
        if session_expires_at is None:
            session_expires_at = float(binding.get("session_expires_at", 0))
        session_remaining = max(0.0, session_expires_at - _now())
        if session_remaining <= 0:
            raise ValueError("This session has expired.")

        access = _token()
        refresh = _token()
        access_expires = _now() + min(self._access_token_ttl, session_remaining)
        access_record: dict[str, Any] = {
            "binding_id": binding_id,
            "client_id": client_id,
            "scopes": scopes,
            "expires_at": access_expires,
            "subject": subject,
        }
        access_record.update(self._protection.wrap(data_key, access))
        refresh_record: dict[str, Any] = {
            "binding_id": binding_id,
            "client_id": client_id,
            "scopes": scopes,
            "expires_at": session_expires_at,
            "subject": subject,
        }
        refresh_record.update(self._protection.wrap(data_key, refresh))

        await self._store.put(
            _hash(access),
            access_record,
            collection=COLLECTION_ACCESS_TOKENS,
            ttl=max(1.0, access_expires - _now()),
        )
        await self._store.put(
            _hash(refresh),
            refresh_record,
            collection=COLLECTION_REFRESH_TOKENS,
            ttl=session_remaining,
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=int(access_expires - _now()),
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[RefreshToken]:
        record = await self._store.get(
            _hash(refresh_token), collection=COLLECTION_REFRESH_TOKENS
        )
        if record is None:
            # A rotated token presented again is reuse (RFC 6819 5.2.2.3):
            # the session is compromised, so end it.
            tombstone = await self._store.get(
                _hash(refresh_token), collection=COLLECTION_ROTATED_REFRESH
            )
            if tombstone is not None:
                logger.warning(
                    "Rotated refresh token presented again; revoking the binding."
                )
                await self.revoke_binding(str(tombstone["binding_id"]))
            return None
        if record.get("client_id") != client.client_id:
            return None
        if float(record.get("expires_at", 0)) < _now():
            return None
        if (
            await self._store.get(record["binding_id"], collection=COLLECTION_BINDINGS)
            is None
        ):
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=record["client_id"],
            scopes=list(record.get("scopes", [])),
            expires_at=int(record["expires_at"]),
            subject=record.get("subject"),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        key = _hash(refresh_token.token)
        record = await self._store.get(key, collection=COLLECTION_REFRESH_TOKENS)
        if record is None:
            raise ValueError("Refresh token is not valid.")
        granted = list(record.get("scopes", []))
        requested = list(scopes) if scopes else granted
        if not set(requested).issubset(set(granted)):
            raise ValueError("Refresh cannot widen the granted scopes.")

        binding_id = str(record["binding_id"])
        session_expires_at = float(record.get("expires_at", 0))
        data_key = self._protection.unwrap(record, refresh_token.token)

        # Claim the old token, then leave a tombstone so a later reuse is
        # recognisable. Two refreshes racing on one live token can both succeed
        # before either tombstone lands; accepted, since a client serialises
        # its own refreshes.
        claimed = await self._store.delete(key, collection=COLLECTION_REFRESH_TOKENS)
        if not claimed:
            raise ValueError("Refresh token is not valid.")
        await self._store.put(
            key,
            {"binding_id": binding_id},
            collection=COLLECTION_ROTATED_REFRESH,
            ttl=max(1.0, session_expires_at - _now()),
        )
        return await self._issue_pair(
            binding_id=binding_id,
            client_id=client.client_id,
            scopes=requested,
            data_key=data_key,
            subject=record.get("subject"),
            session_expires_at=session_expires_at,
        )

    # -- per-request token loading ----------------------------------------

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        record = await self._store.get(
            _hash(token), collection=COLLECTION_ACCESS_TOKENS
        )
        if record is None:
            return None
        if float(record.get("expires_at", 0)) < _now():
            return None
        binding_id = str(record["binding_id"])
        binding_record = await self._store.get(
            binding_id, collection=COLLECTION_BINDINGS
        )
        if binding_record is None:
            # Revocation reaches every token through this dereference; nothing
            # enumerates the token collections.
            return None
        binding = self._protection.unseal(
            binding_record, self._protection.unwrap(record, token)
        )
        if not binding or not binding.get("api_key"):
            return None
        return AccessToken(
            token=token,
            client_id=record.get("client_id") or "",
            scopes=list(record.get("scopes", [])),
            expires_at=int(record["expires_at"]),
            subject=record.get("subject"),
            claims={
                "binding_id": binding_id,
                "redmine_api_key": binding["api_key"],
                "redmine_user_id": binding.get("redmine_user_id"),
                "redmine_login": binding.get("redmine_login"),
            },
        )

    # -- revocation --------------------------------------------------------

    async def revoke_token(self, token: Any) -> None:
        """RFC 7009. Revoking an access token logs out that token only;
        revoking a refresh token ends the session."""
        raw = getattr(token, "token", None)
        if not raw:
            return
        if isinstance(token, RefreshToken):
            record = await self._store.get(
                _hash(raw), collection=COLLECTION_REFRESH_TOKENS
            )
            await self._store.delete(_hash(raw), collection=COLLECTION_REFRESH_TOKENS)
            if record is not None:
                await self.revoke_binding(str(record["binding_id"]))
            return
        await self._store.delete(_hash(raw), collection=COLLECTION_ACCESS_TOKENS)

    async def revoke_binding(self, binding_id: str) -> bool:
        """Delete the binding. Every token pointing at it dies on next use."""
        return await self._store.delete(binding_id, collection=COLLECTION_BINDINGS)


# --- store wiring and factory ------------------------------------------


def _storage_encryption_key(signing_key: str) -> bytes:
    """Derive the storage key exactly the way FastMCP's OAuthProxy does.

    Two hops, both from ``derive_jwt_key``: the operator's secret is
    low-entropy material for the signing key, and that key is high-entropy
    material for the storage key. Mirroring it keeps the two modes' stores
    interchangeable in shape and inherits any future fix upstream makes.
    """
    jwt_key = derive_jwt_key(
        low_entropy_material=signing_key, salt="fastmcp-jwt-signing-key"
    )
    return derive_jwt_key(
        high_entropy_material=jwt_key.decode(),
        salt="fastmcp-storage-encryption-key",
    )


def api_key_login_store_path(signing_key: Optional[str] = None) -> Path:
    """Where the store lives. Resolved per call, so a late ``FASTMCP_HOME``
    is still honoured (the same reason ``oauth_proxy_store_path`` does it).

    Different secrets get different directories, so two servers on one host
    never collide and a rotated secret starts clean instead of failing to
    decrypt someone else's records.
    """
    base = Path(settings.home) / STORE_SUBDIR
    if signing_key is None:
        return base
    fingerprint = hashlib.sha256(_storage_encryption_key(signing_key)).hexdigest()[:12]
    return base / fingerprint


def log_api_key_login_store_path(auth_mode: str) -> None:
    """Log the resolved store directory once at startup.

    Without this, "everyone had to sign in again after the deploy" is very
    hard to trace back to a store that lives inside the container filesystem.
    """
    if auth_mode != "api-key-login":
        return
    logger.info("api-key-login state directory: %s", api_key_login_store_path())
    if not os.getenv("FASTMCP_HOME"):
        logger.warning(
            "FASTMCP_HOME is unset, so the api-key-login store falls back to "
            "the platform data directory. In a container that is discarded on "
            "every rebuild and every user has to sign in again."
        )


def build_store(signing_key: str) -> AsyncKeyValue:
    """A file store under ``FASTMCP_HOME``, encrypted with the operator secret.

    Mirrors what FastMCP's own ``OAuthProxy`` builds for its client storage,
    but under ``api-key-login/`` so the two modes never share a directory.

    ``raise_on_decryption_error=False`` matches upstream: a record written
    under a previous secret reads as a miss rather than an exception, so
    rotating the key signs everyone out instead of crashing the server.
    """
    encryption_key = _storage_encryption_key(signing_key)
    directory = api_key_login_store_path(signing_key)
    directory.mkdir(parents=True, exist_ok=True)
    file_store = FileTreeStore(
        data_directory=directory,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(directory),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(
            directory
        ),
    )
    return FernetEncryptionWrapper(
        key_value=file_store,
        fernet=Fernet(key=encryption_key),
        raise_on_decryption_error=False,
    )


def build_api_key_login() -> ApiKeyLoginProvider:
    """Construct the provider from the environment, failing fast.

    Kept here rather than in ``_env.py`` for the same reason
    ``build_oauth_proxy`` lives in ``_oauth_proxy.py``: the factory belongs
    next to the thing it builds, and the import stays lazy so legacy
    deployments never load it.
    """
    redmine_url = get_required(
        "REDMINE_URL",
        error_text="api-key-login validates pasted keys against this Redmine.",
    )
    base_url = get_required(
        "REDMINE_MCP_BASE_URL",
        error_text=(
            "api-key-login advertises this URL as its issuer and redirects the "
            "browser here, so it must be the address clients can reach."
        ),
    ).rstrip("/")
    signing_key = get_required_secret(
        "REDMINE_MCP_JWT_SIGNING_KEY",
        error_text=(
            "api-key-login derives its storage encryption key from this value. "
            "Changing it invalidates every session."
        ),
    )

    allow_http = _is_true_env("REDMINE_API_KEY_LOGIN_ALLOW_HTTP")
    if base_url.startswith("http://") and not allow_http:
        raise RuntimeError(
            "REDMINE_MCP_BASE_URL must be https in api-key-login mode: the "
            "login page carries a Redmine API key. Set "
            "REDMINE_API_KEY_LOGIN_ALLOW_HTTP=true for local development only."
        )

    session_days = _get_int_env(
        "REDMINE_API_KEY_LOGIN_SESSION_DAYS", DEFAULT_SESSION_DAYS
    )
    provider = ApiKeyLoginProvider(
        base_url=base_url,
        redmine_url=redmine_url,
        store=build_store(signing_key),
        scopes_supported=configured_advertised_scopes(),
        allowed_client_redirect_uris=get_allowed_client_redirect_uris(),
        allow_admin=_is_true_env("REDMINE_API_KEY_LOGIN_ALLOW_ADMIN"),
        session_ttl=session_days * 86400,
    )
    logger.warning(
        "api-key-login mode active. This server now stores full-power Redmine "
        "API keys, encrypted at rest under REDMINE_MCP_JWT_SIGNING_KEY; whoever "
        "holds both the store and that secret can read them. The store is "
        "node-local, so a second replica will not see these sessions."
    )
    return provider
