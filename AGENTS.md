# Repository Guidelines for Codex Agents

This file provides instructions for any Codex agent interacting with this repository.

## Setup
- Requires **Python 3.13+** and the [`uv`](https://docs.astral.sh/uv/) package manager.
- Create a virtual environment and install dependencies:
  ```bash
  uv venv
  source .venv/bin/activate
  uv pip install -e .
  ```
- Install development/test requirements with:
  ```bash
  uv pip install pytest pytest-asyncio pytest-cov pytest-mock
  ```

## Running the Server
- Development mode:
  ```bash
  uv run fastapi dev src/redmine_mcp_server/main.py
  ```
- Production mode:
  ```bash
  uv run python src/redmine_mcp_server/main.py
  ```

## Testing
Use the provided test runner located in `tests/run_tests.py`.

- Run **all** tests:
  ```bash
  python tests/run_tests.py --all
  ```
- Run **unit** tests only:
  ```bash
  python tests/run_tests.py
  ```
- Run **integration** tests only:
  ```bash
  python tests/run_tests.py --integration
  ```
- Generate a coverage report:
  ```bash
  python tests/run_tests.py --coverage
  ```

Integration tests require a reachable Redmine instance configured via environment variables.

## Docker Usage
- Recommended workflow with `docker-compose`:
  ```bash
  cp .env.example .env.docker
  # Edit .env.docker with your Redmine configuration
  docker-compose up --build
  ```
- Or build and run directly with Docker:
  ```bash
  docker build -t redmine-mcp-server .
  docker run -p 8000:8000 --env-file .env.docker redmine-mcp-server
  ```

## Environment Configuration
Copy `.env.example` to `.env` and set:

- `REDMINE_URL` – base URL of your Redmine server
- `REDMINE_USERNAME` and `REDMINE_PASSWORD` **or** `REDMINE_API_KEY`
- `SERVER_HOST` and `SERVER_PORT` to control server binding

Do **not** commit `.env` or other secrets to version control.

## Licensing
This project uses the MIT License. See `LICENSE` for details.
