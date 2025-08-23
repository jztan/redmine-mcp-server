"""
Native FastAPI server for AWS AgentCore integration.

AWS AgentCore is Amazon's service for deploying AI agents and MCP servers in 
cloud environments. This module provides direct MCP protocol handling without 
FastMCP complexity, optimized for AWS cloud deployment scenarios.

It uses the shared RedmineTools class for consistent business logic across
transport modes.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional
import logging

from .redmine_tools import RedmineTools, get_redmine_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MCPRequest(BaseModel):
    """MCP JSON-RPC request model."""
    jsonrpc: str = "2.0"
    method: str
    params: Dict[str, Any] = {}
    id: int


class MCPResponse(BaseModel):
    """MCP JSON-RPC response model."""
    jsonrpc: str = "2.0"
    result: Optional[Any] = None
    error: Optional[Any] = None
    id: int


# Initialize FastAPI app
app = FastAPI(
    title="Redmine MCP Server - AgentCore",
    description="Native FastAPI server for MCP protocol handling",
    version="1.0.0",
    docs_url=None,  # Disable for security
    redoc_url=None
)

# Initialize tools with Redmine client
tools = RedmineTools(get_redmine_client())

# Tool definitions for MCP tools/list
TOOL_DEFINITIONS = [
    {
        "name": "get_redmine_issue",
        "description": "Get detailed information about a Redmine issue",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "integer", "description": "The ID of the issue to retrieve"},
                "include_journals": {"type": "boolean", "default": True, "description": "Whether to include journals (comments)"},
                "include_attachments": {"type": "boolean", "default": True, "description": "Whether to include attachments metadata"}
            },
            "required": ["issue_id"]
        }
    },
    {
        "name": "list_redmine_projects",
        "description": "List all accessible Redmine projects",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "list_my_redmine_issues",
        "description": "List issues assigned to the current user",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Filter by project ID"},
                "status_id": {"type": "integer", "description": "Filter by status ID"},
                "priority_id": {"type": "integer", "description": "Filter by priority ID"},
                "limit": {"type": "integer", "description": "Maximum number of issues to return"}
            },
            "required": []
        }
    },
    {
        "name": "search_redmine_issues",
        "description": "Search Redmine issues matching a query string",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for in issues"},
                "project_id": {"type": "integer", "description": "Limit search to specific project"},
                "status_id": {"type": "integer", "description": "Filter by status ID"},
                "limit": {"type": "integer", "description": "Maximum number of results to return"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "create_redmine_issue",
        "description": "Create a new issue in Redmine",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "ID of the project to create issue in"},
                "subject": {"type": "string", "description": "Issue subject/title"},
                "description": {"type": "string", "description": "Issue description"},
                "priority_id": {"type": "integer", "description": "Priority ID"},
                "assigned_to_id": {"type": "integer", "description": "Assignee user ID"},
                "status_id": {"type": "integer", "description": "Status ID"}
            },
            "required": ["project_id", "subject"]
        }
    },
    {
        "name": "update_redmine_issue",
        "description": "Update an existing Redmine issue",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "integer", "description": "ID of the issue to update"},
                "fields": {
                    "type": "object",
                    "description": "Dictionary of fields to update",
                    "properties": {
                        "subject": {"type": "string"},
                        "description": {"type": "string"},
                        "status_id": {"type": "integer"},
                        "status_name": {"type": "string", "description": "Status name (convenience field)"},
                        "priority_id": {"type": "integer"},
                        "assigned_to_id": {"type": "integer"},
                        "notes": {"type": "string", "description": "Journal note to add"}
                    }
                }
            },
            "required": ["issue_id", "fields"]
        }
    },
    {
        "name": "download_redmine_attachment",
        "description": "Download a Redmine attachment and return the saved file path",
        "inputSchema": {
            "type": "object",
            "properties": {
                "attachment_id": {"type": "integer", "description": "The ID of the attachment to download"},
                "save_dir": {"type": "string", "default": ".", "description": "Directory where the file will be saved"}
            },
            "required": ["attachment_id"]
        }
    },
    {
        "name": "summarize_project_status",
        "description": "Provide a summary of project status based on issue activity",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "The ID of the project to summarize"},
                "days": {"type": "integer", "default": 30, "description": "Number of days to look back for analysis"}
            },
            "required": ["project_id"]
        }
    }
]


@app.get("/health")
async def health():
    """Health check endpoint for AWS load balancers and monitoring."""
    return {
        "status": "healthy", 
        "mode": "agentcore",
        "redmine_connected": tools.client is not None
    }


@app.post("/mcp", response_model=MCPResponse)  
async def handle_mcp(request: MCPRequest) -> MCPResponse:
    """Direct MCP protocol handling without FastMCP complexity."""
    
    try:
        logger.info(f"MCP request: {request.method} with params: {request.params}")
        
        if request.method == "tools/list":
            result = {"tools": TOOL_DEFINITIONS}
            
        elif request.method == "tools/call":
            tool_name = request.params.get("name")
            tool_args = request.params.get("arguments", {})
            
            # Direct method dispatch to RedmineTools
            if hasattr(tools, tool_name):
                logger.info(f"Calling tool: {tool_name} with args: {tool_args}")
                result = await getattr(tools, tool_name)(**tool_args)
            else:
                logger.error(f"Unknown tool: {tool_name}")
                raise HTTPException(status_code=400, detail=f"Unknown tool: {tool_name}")
                
        else:
            logger.error(f"Unknown method: {request.method}")
            raise HTTPException(status_code=400, detail=f"Unknown method: {request.method}")
        
        logger.info(f"MCP response: success")
        return MCPResponse(result=result, id=request.id)
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error handling MCP request: {e}")
        return MCPResponse(
            error={"code": -32603, "message": "Internal error", "data": str(e)}, 
            id=request.id
        )


if __name__ == "__main__":
    import uvicorn
    
    # Check if tools are properly initialized
    if not tools.client:
        logger.warning("Redmine client not initialized. Check environment variables.")
        logger.warning("Required: REDMINE_URL and (REDMINE_API_KEY or REDMINE_USERNAME/REDMINE_PASSWORD)")
    else:
        logger.info("Redmine client initialized successfully")
    
    # Run the server
    uvicorn.run(app, host="0.0.0.0", port=8000)