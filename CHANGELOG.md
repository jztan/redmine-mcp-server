# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.2] - 2025-05-26

### Added
- New MCP tools `create_redmine_issue` and `update_redmine_issue` for managing issues
- Documentation updates describing the new tools
- Integration tests for issue creation and update

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

