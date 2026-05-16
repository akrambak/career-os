"""Regression test for the dashboard CLI subprocess call.

Bug history: the CLI originally called `subprocess.run(["streamlit", ...])`,
which only worked when the venv was activated (i.e. when .venv/bin was on
PATH). Users running `.venv/bin/career-os dashboard` directly hit
FileNotFoundError because `streamlit` wasn't resolvable. Fix: invoke via
the current interpreter using `sys.executable -m streamlit`. This test
pins that invocation shape so it can't regress silently.
"""
from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from career_os.cli.main import cli

# `subprocess.run` is used in two distinct call sites:
#   1. hostname -I       (in dashboard/network.py — network detection)
#   2. python -m streamlit (in cli/main.py — the actual launch)
# Patching the bare module's `run` swaps both. We use a side_effect that
# returns a real-ish result for hostname and None-equivalent for streamlit,
# then filter the call list to assert only on the streamlit invocation.

_REAL_RUN = subprocess.run


def _passthrough_for_hostname(*args, **kwargs):
    """Let `hostname -I` run for real; intercept everything else."""
    cmd = args[0] if args else kwargs.get("args")
    if isinstance(cmd, list) and cmd and cmd[0] == "hostname":
        return _REAL_RUN(*args, **kwargs)
    return MagicMock(returncode=0, stdout="", stderr="")


def _streamlit_call(mock_run):
    for call in mock_run.call_args_list:
        cmd = call.args[0] if call.args else call.kwargs.get("args")
        if isinstance(cmd, list) and "streamlit" in cmd:
            return cmd
    raise AssertionError(
        f"No streamlit launch in subprocess.run calls: {mock_run.call_args_list!r}"
    )


def test_dashboard_invokes_python_dash_m_streamlit():
    runner = CliRunner()
    # Patch only the cli.main namespace so the network-probe subprocess call
    # in dashboard/network.py still runs normally.
    with patch("subprocess.run", side_effect=_passthrough_for_hostname) as mock_run:
        result = runner.invoke(cli, ["dashboard", "--no-open", "--port", "9999"])
    assert result.exit_code == 0, result.output
    cmd = _streamlit_call(mock_run)
    # MUST use the current interpreter, not bare `streamlit` on PATH.
    assert cmd[0] == sys.executable, f"expected {sys.executable!r}, got {cmd[0]!r}"
    assert cmd[1] == "-m"
    assert cmd[2] == "streamlit"
    assert cmd[3] == "run"
    # The script path should be a real file we can resolve.
    from pathlib import Path
    assert Path(cmd[4]).exists(), f"app.py not found at {cmd[4]}"
    # Port + bind address pass through.
    assert "--server.port" in cmd and "9999" in cmd
    assert "--server.address" in cmd and "0.0.0.0" in cmd


def test_dashboard_passes_custom_address():
    runner = CliRunner()
    with patch("subprocess.run", side_effect=_passthrough_for_hostname) as mock_run:
        result = runner.invoke(cli, ["dashboard", "--no-open", "--address", "127.0.0.1"])
    assert result.exit_code == 0
    cmd = _streamlit_call(mock_run)
    addr_idx = cmd.index("--server.address")
    assert cmd[addr_idx + 1] == "127.0.0.1"


def test_dashboard_diagnose_exits_without_subprocess():
    """--diagnose should print and exit, never invoking streamlit."""
    runner = CliRunner()
    with patch("subprocess.run", side_effect=_passthrough_for_hostname) as mock_run:
        result = runner.invoke(cli, ["dashboard", "--diagnose"])
    assert result.exit_code == 0
    # No streamlit invocation at all when --diagnose is set.
    streamlit_calls = [
        c for c in mock_run.call_args_list
        if isinstance(c.args[0], list) and "streamlit" in c.args[0]
    ]
    assert streamlit_calls == []
    # The output should mention WSL recipes (we ARE on WSL in this dev env;
    # for non-WSL CI the assertion below still passes because we always
    # render either the WSL block or the non-WSL block).
    assert "Network diagnostics" in result.output
