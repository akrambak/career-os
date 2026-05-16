"""Network detection + URL hints for the dashboard CLI.

Split from cli/main.py so it's importable from anywhere and unit-testable
without booting Streamlit.
"""
from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Environment:
    is_wsl: bool
    is_docker: bool
    primary_ip: str | None  # the LAN/WSL2 IP (not loopback)
    hostname: str


def detect_environment() -> Environment:
    return Environment(
        is_wsl=_is_wsl(),
        is_docker=_is_docker(),
        primary_ip=_primary_ip(),
        hostname=socket.gethostname(),
    )


def _is_wsl() -> bool:
    """WSL kernels include 'microsoft' or 'WSL' in /proc/version."""
    p = Path("/proc/version")
    if not p.exists():
        return False
    try:
        content = p.read_text().lower()
    except OSError:
        return False
    return "microsoft" in content or "wsl" in content


def _is_docker() -> bool:
    return Path("/.dockerenv").exists()


def _primary_ip() -> str | None:
    """First non-loopback IPv4 address from `hostname -I`, or None."""
    try:
        out = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    parts = out.stdout.split()
    for p in parts:
        if p and not p.startswith("127.") and ":" not in p:  # skip loopback + IPv6
            return p
    return None


def build_reachable_urls(env: Environment, address: str, port: int) -> list[tuple[str, str]]:
    """Return [(label, url), ...] in preferred-try order for the user's environment."""
    urls: list[tuple[str, str]] = []
    if address == "127.0.0.1":
        urls.append(("loopback only", f"http://127.0.0.1:{port}"))
        return urls
    # 0.0.0.0 or any other bind that accepts traffic from anywhere
    urls.append(("localhost (Windows via WSL forwarding)" if env.is_wsl else "localhost",
                 f"http://localhost:{port}"))
    if env.primary_ip:
        label = "WSL2 IP — use if localhost fails" if env.is_wsl else "LAN IP"
        urls.append((label, f"http://{env.primary_ip}:{port}"))
    return urls


def render_diagnostics(env: Environment, port: int) -> str:
    """Long-form diagnostic block to help debug Windows-side networking."""
    lines: list[str] = []
    lines.append("[bold]Network diagnostics[/bold]\n")
    lines.append(f"  Hostname:   {env.hostname}")
    lines.append(f"  Primary IP: {env.primary_ip or '(none detected)'}")
    lines.append(f"  WSL2:       {'yes' if env.is_wsl else 'no'}")
    lines.append(f"  Docker:     {'yes' if env.is_docker else 'no'}")
    lines.append("")
    if env.is_wsl:
        ip = env.primary_ip or "<WSL_IP>"
        lines.append("[bold]WSL2 detected — recipes for the Windows side[/bold]\n")
        lines.append("[bold]1. From your Windows browser, try these in order:[/bold]")
        lines.append(f"   a) http://localhost:{port}              [dim](usually works)[/dim]")
        lines.append(f"   b) http://{ip}:{port}            [dim](explicit WSL2 IP)[/dim]")
        lines.append("")
        lines.append("[bold]2. If localhost fails but the IP works:[/bold]")
        lines.append("   WSL's localhost forwarding is stale. From Windows PowerShell:")
        lines.append("   [bold]   wsl --shutdown[/bold]")
        lines.append("   Then start your shell again and re-run `career-os dashboard`.")
        lines.append("")
        lines.append("[bold]3. If BOTH fail:[/bold]")
        lines.append("   a) Windows Firewall is blocking WSL. From PowerShell (Admin):")
        lines.append("   [bold]   New-NetFirewallRule -DisplayName 'WSL Career-OS' \\\n"
                     f"        -Direction Inbound -InterfaceAlias 'vEthernet (WSL*)' \\\n"
                     f"        -Action Allow -Protocol TCP -LocalPort {port}[/bold]")
        lines.append("")
        lines.append("   b) Or set up an explicit port-forward (PowerShell, Admin):")
        lines.append(f"   [bold]   netsh interface portproxy add v4tov4 listenport={port} \\\n"
                     f"        listenaddress=0.0.0.0 connectport={port} connectaddress={ip}[/bold]")
        lines.append("")
        lines.append("[bold]4. Permanent fix: enable WSL2 mirrored networking[/bold]")
        lines.append("   Requires WSL 2.0.0+ and Windows 11 22H2+.")
        lines.append("   Edit (or create) [bold]C:\\Users\\<you>\\.wslconfig[/bold] with:")
        # Escape the literal [wsl2] section header for rich's markup parser.
        lines.append("   [bold]   \\[wsl2]\n"
                     "        networkingMode=mirrored[/bold]")
        lines.append("   Then in PowerShell: [bold]wsl --shutdown[/bold]. Reopen WSL.")
        lines.append("   After that, localhost from Windows = localhost in WSL, always.")
    else:
        lines.append("[bold]Not running under WSL.[/bold]")
        lines.append(f"  Visit http://localhost:{port} from this machine, or")
        lines.append(f"  http://{env.primary_ip or '<IP>'}:{port} from another device on the LAN.")
    lines.append("")
    lines.append(
        "[dim]Run `career-os dashboard` (without --diagnose) to actually launch.[/dim]"
    )
    return "\n".join(lines)
