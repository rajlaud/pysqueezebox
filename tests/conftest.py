"""Common functions and fixtures for pysqueezebox tests."""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add the command-line options."""
    parser.addoption(
        "--host",
        type=str,
        default=None,
        action="store",
        dest="HOST",
        help="LMS host to use for integration tests",
    )

    parser.addoption(
        "--port",
        type=int,
        default=9000,
        action="store",
        dest="PORT",
        help="LMS port to use for integration tests",
    )

    parser.addoption(
        "--https",
        type=bool,
        default=False,
        action="store",
        dest="HTTPS",
        help="whether to use https to connect",
    )

    parser.addoption(
        "--prefer-player",
        type=str,
        default=None,
        action="append",
        dest="PREFER",
        help="prefer this player in tests",
    )

    parser.addoption(
        "--exclude-player",
        type=str,
        default=None,
        action="append",
        dest="EXCLUDE",
        help="exclude this player from being used in tests",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark live-server tests before marker-based selection."""
    integration_module = Path(__file__).with_name("test_integration.py")
    for item in items:
        if item.path == integration_module:
            item.add_marker(pytest.mark.integration)


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip tests marked 'integration' unless an ip address is given."""
    if "integration" in item.keywords and not item.config.getoption("--host"):
        pytest.skip("Use --host to specify an LMS server for live tests.")
