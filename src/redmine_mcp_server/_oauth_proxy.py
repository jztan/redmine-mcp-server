"""FastMCP OAuthProxy factory for Redmine OAuth."""

from __future__ import annotations

import os

from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier
from pydantic import AnyHttpUrl

from ._env import get_required, get_required_secret, get_secret
from .oauth_scopes import advertised_scopes

INTROSPECTION_GUIDANCE = (
    "Register a confidential OAuth client in Redmine and configure "
    "Doorkeeper's allow_token_introspection block to accept it "
    "(see docs/oauth-setup.md Step 2 for the walkthrough)."
)


def _redmine_endpoint(redmine_url: str, path: str) -> AnyHttpUrl:
    """Build a Redmine OAuth endpoint URL from a Redmine issuer URL."""
    return AnyHttpUrl(f"{str(AnyHttpUrl(redmine_url)).rstrip('/')}/{path.lstrip('/')}")


def build_oauth_proxy() -> OAuthProxy:
    """Construct FastMCP OAuthProxy for Redmine-backed OAuth."""
    redmine_url = get_required(
        "REDMINE_URL",
        error_text="OAuth proxy mode requires this value. See docs/oauth-setup.md.",
    )
    base_url = get_required(
        "REDMINE_MCP_BASE_URL",
        error_text=(
            "OAuth proxy mode requires this value. "
            "Set it to the public MCP base URL."
        ),
    )
    upstream_client_id = os.getenv("REDMINE_OAUTH_CLIENT_ID") or get_required(
        "REDMINE_INTROSPECT_CLIENT_ID",
        error_text=INTROSPECTION_GUIDANCE,
    )
    upstream_client_secret = get_secret("REDMINE_OAUTH_CLIENT_SECRET") or (
        get_required_secret(
            "REDMINE_INTROSPECT_CLIENT_SECRET",
            error_text=INTROSPECTION_GUIDANCE,
        )
    )
    jwt_signing_key = get_required_secret(
        "REDMINE_MCP_JWT_SIGNING_KEY",
        error_text=(
            "OAuth proxy mode requires this value. FastMCP uses it to sign "
            "proxy tokens and derive encrypted storage."
        ),
    )
    introspect_client_id = get_required(
        "REDMINE_INTROSPECT_CLIENT_ID",
        error_text=INTROSPECTION_GUIDANCE,
    )
    introspect_client_secret = get_required_secret(
        "REDMINE_INTROSPECT_CLIENT_SECRET",
        error_text=INTROSPECTION_GUIDANCE,
    )

    verifier = IntrospectionTokenVerifier(
        introspection_url=str(_redmine_endpoint(redmine_url, "/oauth/introspect")),
        client_id=introspect_client_id,
        client_secret=introspect_client_secret,
    )

    return OAuthProxy(
        upstream_authorization_endpoint=str(
            _redmine_endpoint(redmine_url, "/oauth/authorize")
        ),
        upstream_token_endpoint=str(_redmine_endpoint(redmine_url, "/oauth/token")),
        upstream_client_id=upstream_client_id,
        upstream_client_secret=upstream_client_secret,
        upstream_revocation_endpoint=str(
            _redmine_endpoint(redmine_url, "/oauth/revoke")
        ),
        token_verifier=verifier,
        base_url=base_url,
        jwt_signing_key=jwt_signing_key,
        valid_scopes=advertised_scopes(),
        require_authorization_consent="external",
    )
