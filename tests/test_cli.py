"""CLI smoke tests.

`chronicle --version` shipped broken in 0.1.0 because click looked up the
distribution by the import name (`chronicle`) instead of `agent-chronicle`.
These guard the entry point against that class of regression.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from chronicle import __version__
from chronicle.cli import main


@pytest.mark.layer1
def test_version_flag_does_not_crash():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output


@pytest.mark.layer1
def test_help_lists_commands():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for command in ("record", "replay", "verify", "show-graph", "schema"):
        assert command in result.output
