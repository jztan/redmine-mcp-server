# Changelog

All notable changes to this project will be documented in this file.


The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2025-09-21

### Added
- **Automatic file cleanup system** with configurable intervals and expiry times
- `AUTO_CLEANUP_ENABLED` environment variable for enabling/disabling automatic cleanup (default: true)
- `CLEANUP_INTERVAL_MINUTES` environment variable for cleanup frequency (default: 10 minutes)
- `ATTACHMENT_EXPIRES_MINUTES` environment variable for default attachment expiry (default: 60 minutes)
- Background cleanup task with lazy initialization via MCP tool calls
- Cleanup status endpoint (`/cleanup/status`) for monitoring background task
- `CleanupTaskManager` class for managing cleanup task lifecycle
- Enhanced health check endpoint with cleanup task initialization
- Comprehensive file management configuration documentation in README

### Changed
- **BREAKING**: `CLEANUP_INTERVAL_HOURS` replaced with `CLEANUP_INTERVAL_MINUTES` for finer control
- Default attachment expiry configurable via environment variable instead of hardcoded 24 hours
- Cleanup task now starts automatically when first MCP tool is called (lazy initialization)
- Updated `.env.example` with new minute-based configuration options

### Improved
- More granular control over cleanup timing with minute-based intervals
- Better resource management with automatic cleanup task lifecycle
- Enhanced monitoring capabilities with cleanup status endpoint
- Clearer documentation with practical configuration examples for development and production

## [0.2.1] - 2025-09-20

### Added
- HTTP file serving endpoint (`/files/{file_id}`) for downloaded attachments
- Secure UUID-based file URLs with automatic expiry (24 hours default)
- New `file_manager.py` module for attachment storage and cleanup management
- `cleanup_attachment_files` MCP tool for expired file management
- PUBLIC_HOST/PUBLIC_PORT environment variables for external URL generation
- PEP 8 compliance standards and development tools (flake8, black)
- Storage statistics tracking for attachment management

### Changed
- **BREAKING**: `download_redmine_attachment` now returns `download_url` instead of `file_path`
- Attachment downloads now provide HTTP URLs for external access
- Docker URL generation fixed (uses localhost instead of 0.0.0.0)
- Dependencies optimized (httpx moved to dev/test dependencies)

### Fixed
- Docker container URL accessibility issues for downloaded attachments
- URL generation for external clients in containerized environments

### Improved
- Code quality with full PEP 8 compliance across all Python modules
- Test coverage for new HTTP URL return format
- Documentation updated with file serving details

## [0.2.0] - 2025-09-20

### Changed
- **BREAKING**: Migrated from FastAPI/SSE to FastMCP streamable HTTP transport
- **BREAKING**: MCP endpoint changed from `/sse` to `/mcp`
- Updated server architecture to use FastMCP's native HTTP capabilities
- Simplified initialization and removed FastAPI dependency layer

### Added
- Native FastMCP streamable HTTP transport support
- Claude Code CLI setup command documentation
- Stateless HTTP mode for better scalability
- Smart issue summarization tool with comprehensive project analytics

### Improved
- Better MCP protocol compliance with native FastMCP implementation
- Reduced complexity by removing custom FastAPI/SSE layer
- Updated all documentation to reflect new transport method
- Enhanced health check endpoint with service identification

### Migration Notes
- Existing MCP clients need to update endpoint from `/sse` to `/mcp`
- Claude Code users can now use: `claude mcp add --transport http redmine http://127.0.0.1:8000/mcp`
- Server initialization simplified with `mcp.run(transport="streamable-http")`

## [0.1.6] - 2025-06-19
### Added
- New MCP tool `search_redmine_issues` for querying issues by text.

## [0.1.5] - 2025-06-18
### Added
- `get_redmine_issue` can now return attachment metadata via a new
  `include_attachments` parameter.
- New MCP tool `download_redmine_attachment` for downloading attachments.

## [0.1.4] - 2025-05-28

### Removed
- Deprecated `get_redmine_issue_comments` tool. Use `get_redmine_issue` with
  `include_journals=True` to retrieve comments.

### Changed
- `get_redmine_issue` now includes issue journals by default. A new
  `include_journals` parameter allows opting out of comment retrieval.

## [0.1.3] - 2025-05-27

### Added
- New MCP tool `list_my_redmine_issues` for retrieving issues assigned to the current user
- New MCP tool `get_redmine_issue_comments` for retrieving issue comments
## [0.1.2] - 2025-05-26

### Changed
- Roadmap moved to its own document with updated plans
- Improved README badges and links

### Added
- New MCP tools `create_redmine_issue` and `update_redmine_issue` for managing issues
- Documentation updates describing the new tools
- Integration tests for issue creation and update
- Integration test for Redmine issue management

## [0.1.1] - 2025-05-25

### Changed
- Updated project documentation with correct repository URLs
- Updated LICENSE with proper copyright (2025 Kevin Tan and contributors)
- Enhanced VS Code integration documentation
- Improved .gitignore to include test coverage files


## [0.1.0] - 2025-05-25

### Added
- Initial release of Redmine MCP Server
- MIT License for open source distribution
- Core MCP server implementation with FastAPI and SSE transport
- Two primary MCP tools:
  - `get_redmine_issue(issue_id)` - Retrieve detailed issue information
  - `list_redmine_projects()` - List all accessible Redmine projects
- Comprehensive authentication support (username/password and API key)
- Modern Python project structure with uv package manager
- Complete testing framework with 20 tests:
  - 10 unit tests for core functionality
  - 7 integration tests for end-to-end workflows
  - 3 connection validation tests
- Docker containerization support:
  - Multi-stage Dockerfile with security hardening
  - Docker Compose configuration with health checks
  - Automated deployment script with comprehensive management
  - Production-ready container setup with non-root user
- Comprehensive documentation:
  - Detailed README.md with installation and usage instructions
  - Complete API documentation with examples
  - Docker deployment guide
  - Testing framework documentation
- Git Flow workflow implementation with standard branching strategy
- Environment configuration templates and examples
- Advanced test runner with coverage reporting and flexible execution

### Technical Features
- **Architecture**: FastAPI application with Server-Sent Events (SSE) transport
- **Security**: Authentication with Redmine instances, non-root Docker containers
- **Testing**: pytest framework with mocks, fixtures, and comprehensive coverage
- **Deployment**: Docker support with automated scripts and health monitoring
- **Documentation**: Complete module docstrings and user guides
- **Development**: Modern Python toolchain with uv, Git Flow, and automated testing

### Dependencies
- Python 3.13+
- FastAPI with standard extensions
- MCP CLI tools
- python-redmine for Redmine API integration
- Docker for containerization
- pytest ecosystem for testing

### Compatibility
- Compatible with Redmine 3.x and 4.x instances
- Supports both username/password and API key authentication
- Works with Docker and docker-compose
- Tested on macOS and Linux environments

[0.1.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.1
[0.1.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.0
[0.1.2]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.2

