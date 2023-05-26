"""Common functions and fixtures for pysqueezebox tests."""
import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """
    Re-scope the event loop to cover this session. Allows to use one aiohttp session
    for all of the tests.
    """
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


def pytest_addoption(parser):
    """Add the commandline options"""
    parser.addoption(
        "--host",
        type=str,
        default=None,
        action="store",
        dest="HOST",
        help="the host for the squeezebox server to be used for the integration tests",
    )

    parser.addoption(
        "--port",
        type=int,
        default=9000,
        action="store",
        dest="PORT",
        help="the port for the squeezebox server to be used for the integration tests",
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


def pytest_runtest_setup(item):
    """Skip tests marked 'integration' unless an ip address is given."""
    if "integration" in item.keywords and not item.config.getoption("--ip"):
        pytest.skip("use --ip and an ip address to run integration tests.")
