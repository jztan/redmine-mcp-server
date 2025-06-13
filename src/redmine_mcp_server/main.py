
"""
Main entry point for the MCP Redmine server.

This module initializes the FastAPI application, sets up the Server-Sent Events (SSE) transport,
and defines the endpoint for handling SSE connections. It also configures the application to run
with Uvicorn when executed as the main module.

Endpoints:
    - /sse: Handles SSE connections for the MCP server.

Modules:
    - fastapi: For creating the web application and defining endpoints.
    - mcp.server.sse: Provides the SSE server transport.
    - starlette.routing: Used for mounting custom routes.
    - .redmine_handler: Contains the MCP server logic.
    - uvicorn: ASGI server for running the application.
"""
from fastapi import FastAPI, Request
from mcp.server.sse import SseServerTransport
from starlette.routing import Mount
import os
import uvicorn
from .redmine_handler import mcp


app = FastAPI(docs_url=None, redoc_url=None,)

sse = SseServerTransport("/messages/")
app.router.routes.append(Mount("/messages", app=sse.handle_post_message))

@app.get("/sse", tags=["MCP"])
async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as (
        read_stream,
        write_stream,
    ):
        init_options = mcp._mcp_server.create_initialization_options()

        await mcp._mcp_server.run(
            read_stream,
            write_stream,
            init_options,
        )

if __name__ == "__main__":
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
