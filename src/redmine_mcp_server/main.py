"""
Main entry point for the MCP Redmine server.

This module uses FastMCP's native streamable HTTP transport for MCP protocol
communication.
The server runs with built-in HTTP endpoints and handles MCP requests natively.

Endpoints:
    - /mcp: Handles MCP requests via streamable HTTP transport.

Modules:
    - .redmine_handler: Contains the MCP server logic with FastMCP integration.
"""

from .redmine_handler import mcp
import os
from dotenv import load_dotenv

# Export the Starlette/FastAPI app for testing and external use
app = mcp.streamable_http_app()


def main():
    """Main entry point for the console script."""
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

    # Configure FastMCP settings for streamable HTTP transport
    mcp.settings.host = os.getenv("SERVER_HOST", "127.0.0.1")
    mcp.settings.port = int(os.getenv("SERVER_PORT", "8000"))
    mcp.settings.stateless_http = True  # Enable stateless mode

    # Run with streamable HTTP transport
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
