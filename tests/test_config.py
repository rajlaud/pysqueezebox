"""Tests for live-server test selection."""

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("args", "passed", "skipped", "deselected"),
    [
        ((), 1, 1, 0),
        (("--host", "example.invalid"), 2, 0, 0),
        (("-m", "integration"), 0, 1, 1),
        (("-m", "not integration"), 1, 0, 1),
    ],
)
def test_live_test_selection(
    pytester: pytest.Pytester,
    args: tuple[str, ...],
    passed: int,
    skipped: int,
    deselected: int,
) -> None:
    """Select live tests explicitly without connecting to a real server."""
    conftest = Path(__file__).with_name("conftest.py")
    pytester.makeconftest(conftest.read_text())
    pytester.makeini("[pytest]\nmarkers = integration: live-server tests\n")
    pytester.makepyfile(
        test_integration="def test_live_server():\n    pass\n",
        test_unit="def test_unit():\n    pass\n",
    )

    result = pytester.runpytest_subprocess("-q", "--strict-markers", *args)
    result.assert_outcomes(
        passed=passed,
        skipped=skipped,
        deselected=deselected,
    )
