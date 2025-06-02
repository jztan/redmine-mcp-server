# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.2] - 2025-06-02

### Added
- **New MCP Tool**: `list_my_redmine_issues()` with advanced filtering and sorting capabilities
  - Smart group discovery mechanism with dual-method approach for robust group membership detection
  - Advanced filtering by project, status, assignee with flexible parameter support
  - Pagination support with configurable limit and offset
  - Sorting capabilities (priority, updated_on, created_on, id) with ascending/descending order
  - Issue deduplication across user and group assignments
  - Comprehensive error handling for edge cases
- **Enhanced Documentation**:
  - Added comprehensive API documentation for new tool with examples
  - Created detailed ROADMAP.md with 4-phase development plan
  - Updated README.md with new features and enhanced documentation structure
- **Comprehensive Testing**:
  - Added 4 new integration test methods for the new tool
  - Added extensive unit tests with mock fixtures for group assignments
  - Enhanced test coverage for edge cases and error handling
  - Updated tests to use behavior-driven approach focusing on functionality over implementation

### Changed
- Updated project version from 0.1.0 to 0.1.1 in dependencies
- Enhanced redmine_handler.py with improved group discovery logic
- Restructured README.md documentation for better organization
- Moved detailed version history and roadmap to separate ROADMAP.md file
- Updated test philosophy to focus on behavior rather than implementation details

### Technical Improvements
- **Group Discovery**: Implemented dual-method approach (direct fetch + access testing fallback)
- **Error Handling**: Enhanced error handling and logging throughout the new tool
- **Code Quality**: Maintained high test coverage with flexible test assertions
- **Architecture**: Followed established MCP patterns for consistency

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

