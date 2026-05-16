from __future__ import annotations

from unittest.mock import patch

from career_os.dashboard.network import (
    Environment,
    build_reachable_urls,
    detect_environment,
    render_diagnostics,
)


def test_detect_environment_runs_without_error():
    env = detect_environment()
    assert isinstance(env.is_wsl, bool)
    assert isinstance(env.is_docker, bool)
    assert env.hostname  # always present


def test_build_reachable_urls_loopback_bind_only_lists_loopback():
    env = Environment(is_wsl=False, is_docker=False, primary_ip="192.168.1.5", hostname="x")
    urls = build_reachable_urls(env, "127.0.0.1", 8501)
    assert len(urls) == 1
    assert urls[0][1] == "http://127.0.0.1:8501"


def test_build_reachable_urls_wide_bind_includes_ip():
    env = Environment(is_wsl=True, is_docker=False, primary_ip="172.29.69.248", hostname="x")
    urls = build_reachable_urls(env, "0.0.0.0", 8501)
    found = [u for _, u in urls]
    assert "http://localhost:8501" in found
    assert "http://172.29.69.248:8501" in found
    # WSL label should hint at the fallback role
    wsl_labels = [label for label, _ in urls if "WSL2 IP" in label]
    assert len(wsl_labels) == 1


def test_build_reachable_urls_no_primary_ip_falls_back_gracefully():
    env = Environment(is_wsl=False, is_docker=False, primary_ip=None, hostname="x")
    urls = build_reachable_urls(env, "0.0.0.0", 8501)
    assert len(urls) == 1
    assert urls[0][1] == "http://localhost:8501"


def test_render_diagnostics_wsl_includes_powershell_recipes():
    env = Environment(is_wsl=True, is_docker=False, primary_ip="172.29.69.248", hostname="x")
    text = render_diagnostics(env, 8501)
    assert "WSL2 detected" in text
    assert "wsl --shutdown" in text
    assert "netsh interface portproxy" in text
    assert "172.29.69.248" in text  # the actual IP appears in recipes
    assert "8501" in text
    assert "networkingMode=mirrored" in text
    # The [wsl2] section header literal must survive rich's markup parser
    # (escaped as \[wsl2] in the source). When rendered, the raw output we
    # build still contains the escape; verify it's there.
    assert "[wsl2]" in text


def test_render_diagnostics_non_wsl_simpler():
    env = Environment(is_wsl=False, is_docker=False, primary_ip="192.168.1.5", hostname="x")
    text = render_diagnostics(env, 8501)
    assert "Not running under WSL" in text
    assert "wsl --shutdown" not in text


def test_detect_environment_with_mocked_wsl_proc(tmp_path, monkeypatch):
    """Verify WSL detection reads /proc/version content."""
    fake_proc = tmp_path / "version"
    fake_proc.write_text("Linux 6.x microsoft-standard-WSL2 ...")
    with patch("career_os.dashboard.network.Path") as mock_path:
        mock_path.return_value = fake_proc
        env = detect_environment()
    assert env.is_wsl is True
