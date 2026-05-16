"""Regression test for the dashboard CLI subprocess call.

Bug history: the CLI originally called `subprocess.run(["streamlit", ...])`,
which only worked when the venv was activated (i.e. when .venv/bin was on
PATH). Users running `.venv/bin/career-os dashboard` directly hit
FileNotFoundError because `streamlit` wasn't resolvable. Fix: invoke via
the current interpreter using `sys.executable -m streamlit`. This test
pins that invocation shape so it can't regress silently.
"""
from __future__ import annotations

import sys
from unittest.mock import patch

from click.testing import CliRunner

from career_os.cli.main import cli


def test_dashboard_invokes_python_dash_m_streamlit():
    runner = CliRunner()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = None
        result = runner.invoke(cli, ["dashboard", "--no-open", "--port", "9999"])
    assert result.exit_code == 0, result.output
    assert mock_run.called
    cmd = mock_run.call_args.args[0]
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
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = None
        result = runner.invoke(cli, ["dashboard", "--no-open", "--address", "127.0.0.1"])
    assert result.exit_code == 0
    cmd = mock_run.call_args.args[0]
    addr_idx = cmd.index("--server.address")
    assert cmd[addr_idx + 1] == "127.0.0.1"
