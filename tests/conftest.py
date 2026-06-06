"""
Configuration file for pytest.

This file configures pytest markers and test settings for the Redmine MCP server tests.
"""

import os
import sys

import pytest


def _integration_run() -> bool:
    """True only when the invocation explicitly targets integration tests.

    Unit runs use ``-m "not integration"`` and the release/full run uses no
    marker; both must be hermetic. The integration-only run (``-m integration``)
    needs the developer's real ``.env`` config, so we leave it alone.
    """
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == "-m" and i + 1 < len(argv):
            return argv[i + 1].strip() == "integration"
        if arg.startswith("-m") and len(arg) > 2:
            return arg[2:].strip() == "integration"
    return False


# Hermeticity guard (must run before any test module imports _client).
#
# A developer's local ``.env`` can define REDMINE_URL + credentials that point
# at a running Redmine. _client loads ``.env`` at import via load_dotenv() and
# re-runs it on every importlib.reload(), so simply deleting these vars in a
# fixture does not hold: the next reload re-adds them. python-dotenv defaults to
# override=False, so pre-seeding the vars as empty strings here makes every
# load_dotenv() a no-op for them. Empty strings read as "unconfigured" by both
# _build_legacy_client() and the /health probe (all checks are truthy tests),
# which is exactly what the unit tests assume.
if not _integration_run():
    for _var in (
        "REDMINE_URL",
        "REDMINE_API_KEY",
        "REDMINE_USERNAME",
        "REDMINE_PASSWORD",
    ):
        os.environ[_var] = ""


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: mark tests as integration tests (require Redmine)",
    )
    config.addinivalue_line(
        "markers",
        "unit: mark tests as unit tests (use mocks, no external dependencies)",
    )


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment before running tests."""
    import os
    import sys

    # Add src to Python path if not already there
    src_path = os.path.join(os.path.dirname(__file__), "..", "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    # Set test environment variable
    os.environ["TESTING"] = "true"

    yield

    # Cleanup after tests
    if "TESTING" in os.environ:
        del os.environ["TESTING"]


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Fixture to mock environment variables for testing."""
    monkeypatch.setenv("REDMINE_URL", "https://test-redmine.example.com")
    monkeypatch.setenv("REDMINE_USERNAME", "test_user")
    monkeypatch.setenv("REDMINE_PASSWORD", "test_password")
    monkeypatch.setenv("SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("SERVER_PORT", "8000")


@pytest.fixture
def mock_api_key_env(monkeypatch):
    """Fixture to mock API key authentication environment."""
    monkeypatch.setenv("REDMINE_URL", "https://test-redmine.example.com")
    monkeypatch.setenv("REDMINE_API_KEY", "test_api_key_12345")
    monkeypatch.setenv("SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("SERVER_PORT", "8000")
    # Remove username/password if they exist
    monkeypatch.delenv("REDMINE_USERNAME", raising=False)
    monkeypatch.delenv("REDMINE_PASSWORD", raising=False)
