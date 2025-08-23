# AWS AgentCore Deployment

This directory contains deployment configuration for the AWS AgentCore HTTP mode of the Redmine MCP server. AWS AgentCore is Amazon's service for deploying AI agents and MCP servers in cloud environments.

## Quick Start

### Local Development

1. **Configure environment**:
   ```bash
   cp .env.agentcore.example .env.agentcore
   # Edit .env.agentcore with your Redmine server details
   ```

2. **Run with Docker Compose**:
   ```bash
   docker-compose -f docker-compose.agentcore.yml up --build
   ```

3. **Test the endpoint**:
   ```bash
   curl http://localhost:8000/health
   ```

### Production Deployment

#### AWS ECS/ECR

1. **Configure AWS deployment**:
   ```bash
   cp .env.agentcore.example .env.agentcore
   # Update with your AWS region and ECR repository
   ```

2. **Deploy**:
   ```bash
   chmod +x deploy.sh
   ./deploy.sh
   ```

3. **Cleanup** (when needed):
   ```bash
   chmod +x cleanup.sh
   ./cleanup.sh
   ```

## API Usage

### Health Check
```bash
GET /health
```

Response:
```json
{
  "status": "healthy",
  "mode": "agentcore", 
  "redmine_connected": true
}
```

### MCP Protocol

#### List Available Tools
```bash
POST /mcp
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "method": "tools/list",
  "id": 1
}
```

#### Call a Tool
```bash
POST /mcp
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "get_redmine_issue",
    "arguments": {
      "issue_id": 123
    }
  },
  "id": 2
}
```

## Available Tools

- `get_redmine_issue` - Get detailed issue information
- `list_redmine_projects` - List all accessible projects  
- `list_my_redmine_issues` - List issues assigned to current user
- `search_redmine_issues` - Search issues by query string
- `create_redmine_issue` - Create new issues
- `update_redmine_issue` - Update existing issues
- `download_redmine_attachment` - Download attachments
- `summarize_project_status` - Get project activity summary

## Configuration

### Environment Variables

- `REDMINE_URL` - Base URL of Redmine instance (required)
- `REDMINE_API_KEY` - API key for authentication (preferred)
- `REDMINE_USERNAME` + `REDMINE_PASSWORD` - Alternative authentication

### Docker Configuration

The AWS AgentCore server runs on port 8000 inside the container. The Dockerfile:

- Uses Python 3.13 slim base image
- Installs required dependencies including FastAPI and uvicorn
- Runs as non-root user for security
- Includes health check endpoint
- Uses proper signal handling for graceful shutdown

## Monitoring

### Health Checks

The server provides a `/health` endpoint that returns:
- Server status
- Mode (agentcore)  
- Redmine connection status

This endpoint is suitable for:
- Docker health checks
- AWS ELB health checks
- Kubernetes liveness/readiness probes

### Logs

The server logs to stdout/stderr with structured logging. Key log events:
- Server startup/shutdown
- MCP request/response
- Redmine client errors
- Tool execution errors

## Security Considerations

- FastAPI documentation endpoints disabled (`docs_url=None`, `redoc_url=None`)
- Runs as non-root user in container
- Environment variables for sensitive configuration
- Proper error handling without information leakage
- Input validation via Pydantic models

## Deployment Management

### Cleanup and Cancellation

When you need to clean up or cancel your AWS AgentCore deployment:

```bash
# Interactive cleanup with confirmations
./cleanup.sh

# Preview what would be deleted (safe)
./cleanup.sh --dry-run

# Clean only Docker resources (local + ECR)
./cleanup.sh --docker-only

# Clean everything without prompts (dangerous)
./cleanup.sh --force
```

The cleanup script handles:
- **ECR Images**: Removes all pushed Docker images
- **ECR Repository**: Optionally deletes the entire repository
- **Local Docker**: Cleans up local images and build cache
- **CloudWatch Logs**: Removes related log groups
- **Safety Features**: Dry-run mode, confirmations, validation

## Architecture Benefits

Compared to the SSE mode, AWS AgentCore provides:

- **Standard HTTP patterns** - Works with any HTTP client/load balancer
- **Better testability** - Standard FastAPI testing approaches work
- **Simpler deployment** - No special runtime requirements
- **Native cloud integration** - Works with AWS ALB, API Gateway, etc.
- **Monitoring friendly** - Standard HTTP status codes and health checks
- **Complete lifecycle management** - Deploy and cleanup scripts included