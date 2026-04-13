"""
Main entry point for the MCP Redmine server.

This module uses FastMCP's native HTTP transport for MCP protocol communication.
The server runs with built-in HTTP endpoints and handles MCP requests natively.

Endpoints:
    - /mcp: Handles MCP requests via streamable HTTP transport.

Modules:
    - .redmine_handler: Contains the MCP server logic with FastMCP integration.
"""

import logging
import os
import uvicorn
import httpx
from importlib.metadata import version, PackageNotFoundError
from starlette.requests import Request
from starlette.responses import JSONResponse

# Configure basic logging before importing modules that log during init
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from .redmine_handler import mcp  # noqa: E402
from .oauth_middleware import RedmineOAuthMiddleware  # noqa: E402

logger = logging.getLogger(__name__)

REDMINE_URL = os.environ.get("REDMINE_URL", "").rstrip("/")
REDMINE_MCP_BASE_URL = os.environ.get(
    "REDMINE_MCP_BASE_URL", "http://localhost:3040"
).rstrip("/")
REDMINE_AUTH_MODE = os.environ.get("REDMINE_AUTH_MODE", "legacy").lower()


def get_version() -> str:
    """Get package version from metadata."""
    try:
        return version("redmine-mcp-server")
    except PackageNotFoundError:
        return "dev"


# --- OAuth2 route handlers (registered conditionally) ---


async def oauth_protected_resource(request: Request):
    """RFC 8707 — Protected Resource Metadata."""
    return JSONResponse(
        {
            "resource": f"{REDMINE_MCP_BASE_URL}/mcp",
            "authorization_servers": [REDMINE_MCP_BASE_URL],
            "bearer_methods_supported": ["header"],
            "resource_name": "Redmine MCP Server",
        }
    )


async def oauth_authorization_server(request: Request):
    """RFC 8414 — Authorization Server Metadata.

    Redmine uses Doorkeeper but does not serve this discovery document itself.
    We serve it manually, pointing to Redmine's real Doorkeeper endpoints.
    """
    return JSONResponse(
        {
            "issuer": REDMINE_MCP_BASE_URL,
            "authorization_endpoint": f"{REDMINE_URL}/oauth/authorize",
            "token_endpoint": f"{REDMINE_URL}/oauth/token",
            "revocation_endpoint": f"{REDMINE_URL}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": [
                "authorization_code",
                "refresh_token",
            ],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
            ],
             "scopes_supported": [
                "view_project", "search_project", "view_members", "add_project",
                "edit_project", "close_project", "delete_project", "select_project_publicity",
                "select_project_modules", "manage_members", "manage_versions", "add_subprojects",
                "manage_public_queries", "save_queries",
                "view_issues", "add_issues", "edit_issues", "edit_own_issues", "copy_issues",
                "manage_issue_relations", "manage_subtasks", "set_issues_private",
                "set_own_issues_private", "add_issue_notes", "edit_issue_notes",
                "edit_own_issue_notes", "view_private_notes", "set_notes_private",
                "delete_issues", "view_issue_watchers", "add_issue_watchers",
                "delete_issue_watchers", "import_issues", "manage_categories",
                "edit_closed_issues", "edit_issue_author", "change_new_issue_author",
                "create_issue_tags", "edit_issue_tags", "view_issue_tags",
                "view_time_entries", "log_time", "edit_time_entries", "edit_own_time_entries",
                "manage_project_activities", "log_time_for_other_users", "import_time_entries",
                "issue_timelog_never_required", "log_time_on_closed_issues",
                "generate_time_entries_reports", "view_time_entries_reports",
                "view_news", "manage_news", "comment_news",
                "view_documents", "add_documents", "edit_documents", "delete_documents",
                "view_files", "manage_files",
                "view_wiki_pages", "view_wiki_edits", "export_wiki_pages", "edit_wiki_pages",
                "rename_wiki_pages", "delete_wiki_pages", "delete_wiki_pages_attachments",
                "view_wiki_page_watchers", "add_wiki_page_watchers", "delete_wiki_page_watchers",
                "protect_wiki_pages", "manage_wiki", "add_wiki_tags",
                "view_changesets", "browse_repository", "commit_access",
                "manage_related_issues", "manage_repository",
                "view_messages", "add_messages", "edit_messages", "edit_own_messages",
                "delete_messages", "delete_own_messages", "view_message_watchers",
                "add_message_watchers", "delete_message_watchers", "manage_boards",
                "view_calendar", "view_gantt",
                "show_hidden_roles_in_memberbox", "set_system_dashboards",
                "share_dashboards", "save_dashboards",
                "manage_public_agile_queries", "add_agile_queries", "view_agile_queries",
                "view_agile_charts", "manage_sprints", "view_backlog", "manage_backlog",
                "view_checklists", "done_checklists", "edit_checklists",
                "manage_checklist_templates",
                "delete_deals", "view_deals", "edit_deals", "add_deals", "manage_deals",
                "delete_deal_watchers", "import_deals",
                "view_contacts", "view_private_contacts", "add_contacts", "edit_contacts",
                "manage_contact_issue_relations", "delete_contacts", "add_notes",
                "delete_notes", "delete_own_notes", "manage_contacts", "import_contacts",
                "export_contacts", "send_contacts_mail", "manage_public_contacts_queries",
                "save_contacts_queries", "manage_public_deals_queries", "save_deals_queries",
                "view_helpdesk_tickets", "view_helpdesk_reports", "send_response",
                "edit_helpdesk_settings", "edit_helpdesk_tickets",
                "manage_public_canned_responses", "manage_canned_responses",
                "view_db_entries", "view_private_db_entries", "add_db_entries",
                "edit_db_entries", "edit_own_db_entries", "delete_db_entries",
                "import_db_entries", "export_db_entries", "set_own_db_entries_private",
                "add_db_entry_notes", "edit_db_entry_notes", "edit_own_db_entry_notes",
                "view_kb_articles", "comment_and_rate_articles", "create_articles",
                "edit_articles", "manage_articles", "manage_own_articles",
                "manage_articles_comments", "create_article_categories",
                "manage_article_categories", "watch_articles", "watch_categories",
                "view_recent_articles", "view_most_popular_articles", "view_top_rated_articles",
                "view_article_history", "manage_article_history",
                "view_passwords", "add_passwords", "edit_passwords", "edit_own_passwords",
                "delete_passwords", "import_passwords", "export_passwords",
                "set_own_passwords_private", "add_password_notes", "edit_password_notes",
                "edit_own_password_notes",
                "manage_report_templates", "generate_issue_reports", "view_issue_reports",
                "send_issue_reports", "view_reporting_files", "view_reporting_log",
                "view_budget", "view_project_tags", "view_reporting_latest_logins",
                "view_project_related_issues", "view_workflow_graph",
                "manage_issue_sla", "view_sla_issues", "issue_sla_executor",
                "admin",
            ],
        }
    )


async def revoke_token(request: Request):
    """RFC 7009 — Revoke an OAuth2 access or refresh token.

    Proxies token revocation to Redmine's Doorkeeper /oauth/revoke endpoint.

    Accepts token via:
    - Authorization header: Bearer <token>
    - POST body: {"token": "<token>"} or form-encoded token=<token>

    Returns:
        200 OK on success (per RFC 7009, even if token was already invalid)
        400 Bad Request if no token provided
        502 Bad Gateway if Redmine is unreachable
    """
    token = None

    # Try Authorization header first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()

    # Fall back to request body
    if not token:
        content_type = request.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
                token = body.get("token")
            except Exception:
                pass
        else:
            # form-encoded
            try:
                form = await request.form()
                token = form.get("token")
            except Exception:
                pass

    if not token:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "error_description": "No token provided",
            },
        )

    # Forward revocation to Redmine's Doorkeeper endpoint
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{REDMINE_URL}/oauth/revoke",
                data={"token": token},
                timeout=10,
            )
        except httpx.RequestError as e:
            logger.error(f"Failed to reach Redmine for token revocation: {e}")
            return JSONResponse(
                status_code=502,
                content={"error": "upstream_unavailable"},
            )

    # RFC 7009: return 200 regardless of whether token was valid
    # (to prevent token scanning attacks)
    if response.status_code in (200, 204):
        return JSONResponse(status_code=200, content={"success": True})

    # If Redmine returns an error, log but still return success per RFC 7009
    logger.warning(
        f"Redmine revocation returned {response.status_code}: " f"{response.text}"
    )
    return JSONResponse(status_code=200, content={"success": True})


def register_oauth_routes(target_app):
    """Register OAuth2 discovery and revocation routes on a Starlette app."""
    target_app.add_route(
        "/.well-known/oauth-protected-resource",
        oauth_protected_resource,
        methods=["GET"],
    )
    target_app.add_route(
        "/.well-known/oauth-authorization-server",
        oauth_authorization_server,
        methods=["GET"],
    )
    target_app.add_route("/revoke", revoke_token, methods=["POST"])


# Export the Starlette app for testing and external use
app = mcp.http_app(stateless_http=True)

# Register OAuth2 middleware and endpoints only when auth mode is oauth
if REDMINE_AUTH_MODE == "oauth":
    app.add_middleware(RedmineOAuthMiddleware)
    register_oauth_routes(app)

# Log version at module load time so it appears regardless of how the server is started
logger.info("Redmine MCP Server v%s", get_version())
logger.info("Auth mode: %s", REDMINE_AUTH_MODE)


def main():
    """Main entry point for the console script."""
    # Note: .env is already loaded during redmine_handler import
    # Note: version/auth mode are logged at module level
    # (works for both direct and uvicorn invocation)

    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))

    # Run with our app directly so custom routes (well-known endpoints) are served
    uvicorn.run(app, host=host, port=port, log_config=None)


if __name__ == "__main__":
    main()
