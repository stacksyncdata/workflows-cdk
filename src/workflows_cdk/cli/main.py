"""
CLI entry point for the Stacksync Workflows CDK.

Registered as a console_script in setup.py so ``pip install workflows-cdk``
makes the ``workflows`` command available globally.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Optional

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.tree import Tree

from ..ai.validator import validate_spec
from ..registry.registry import CapabilityRegistry
from ..spec.compiler import (
    MODULES_DIR,
    compile_connector,
    detect_port,
    needs_content_endpoint,
    needs_schema_endpoint,
)
from ..spec.connector_spec import ConnectorSpec
from ..templates.matcher import match_template

console = Console()

_AUTH_DISPLAY = {
    "oauth2": "OAuth2 via managed connection",
    "api_key": "API key via connection field",
    "basic": "Basic auth",
    "none": "No auth",
}

_BANNER = (
    "[bold cyan]"
    " ____  _             _\n"
    "/ ___|| |_ __ _  ___| | _____ _   _ _ __   ___\n"
    "\\___ \\| __/ _` |/ __| |/ / __| | | | '_ \\ / __|\n"
    " ___) | || (_| | (__| <\\__ \\ |_| | | | | (__\n"
    "|____/ \\__\\__,_|\\___|_|\\_\\___/\\__, |_| |_|\\___|\n"
    "                              |___/"
    "[/bold cyan]"
)


def _print_banner() -> None:
    console.print(_BANNER)
    console.print("[bold green]Workflows CDK[/bold green]")
    console.print("[dim]https://docs.stacksync.com/workflows/app-connector[/dim]")
    console.print()


def _env_file() -> Path:
    return Path.cwd() / ".env"


def _ensure_dotenv() -> None:
    load_dotenv(_env_file())


def _has_api_key() -> bool:
    return bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    )


def _run_setup() -> bool:
    """Interactive first-time setup. Returns True if a key was configured."""
    console.print(
        Panel(
            "[bold]Welcome to Workflows CDK[/bold]\n\n"
            "No API key found. Let's set one up.\n"
            "You can reconfigure anytime with [cyan]workflows setup[/cyan].",
            border_style="blue",
        )
    )

    provider = Prompt.ask(
        "\n[bold]Which AI provider?[/bold]",
        choices=["anthropic", "openai"],
        default="anthropic",
    )

    if provider == "anthropic":
        key_name = "ANTHROPIC_API_KEY"
        hint = "sk-ant-..."
    else:
        key_name = "OPENAI_API_KEY"
        hint = "sk-..."

    api_key = Prompt.ask(f"\n[bold]Paste your {key_name}[/bold] ({hint})")
    api_key = api_key.strip()

    if not api_key:
        console.print("[red]No key provided. Aborting setup.[/red]")
        return False

    os.environ[key_name] = api_key
    _save_to_env(key_name, api_key)

    console.print(f"\n[green bold]Done![/green bold] {key_name} saved to [cyan]{_env_file()}[/cyan]")
    console.print("[dim]You can also export it in your shell or edit .env directly.[/dim]\n")
    return True


def _save_to_env(key_name: str, value: str) -> None:
    """Append or update a key in the .env file."""
    env = _env_file()
    lines: list[str] = []
    found = False

    if env.exists():
        for line in env.read_text().splitlines():
            stripped = line.lstrip("# ").split("=", 1)[0].strip()
            if stripped == key_name:
                lines.append(f"{key_name}={value}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{key_name}={value}")

    env.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

_DOCS_URL = "https://docs.stacksync.com/workflow-automation/developers/build-a-custom-connector"
_NGROK_DOWNLOAD_URL = "https://ngrok.com/download"

# Processes started by this CLI session (Expose with ngrok / background connector).
_managed_ngrok_proc: subprocess.Popen | None = None
_managed_connector_launcher: subprocess.Popen | None = None
_managed_connector_docker_script: bool = False
_managed_connector_project_dir: Path | None = None


def _docker_app_name(project_dir: Path) -> str:
    """Container name used by generated run_dev.sh (workflows-app-<folder>)."""
    return f"workflows-app-{project_dir.resolve().name}"


def _terminate_process_group(proc: subprocess.Popen, *, timeout: float = 8.0) -> None:
    """Stop a process started with start_new_session=True (best-effort)."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        proc.terminate()
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()


def _dispose_managed_ngrok_silent() -> None:
    """Stop ngrok started by this CLI, if still running."""
    global _managed_ngrok_proc
    if _managed_ngrok_proc is not None:
        _terminate_process_group(_managed_ngrok_proc)
        _managed_ngrok_proc = None


def _dispose_managed_connector_silent() -> None:
    """Stop background connector launcher and Docker container if we started them."""
    global _managed_connector_launcher, _managed_connector_docker_script
    global _managed_connector_project_dir

    if _managed_connector_launcher is not None:
        _terminate_process_group(_managed_connector_launcher)
        _managed_connector_launcher = None

    if _managed_connector_docker_script and _managed_connector_project_dir is not None:
        name = _docker_app_name(_managed_connector_project_dir)
        try:
            subprocess.run(
                ["docker", "rm", "-f", name],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    _managed_connector_docker_script = False
    _managed_connector_project_dir = None


def _managed_ngrok_still_running() -> bool:
    global _managed_ngrok_proc
    if _managed_ngrok_proc is None:
        return False
    if _managed_ngrok_proc.poll() is not None:
        _managed_ngrok_proc = None
        return False
    return True


def _managed_connector_still_running() -> bool:
    global _managed_connector_launcher
    if _managed_connector_launcher is None:
        return False
    if _managed_connector_launcher.poll() is not None:
        _managed_connector_launcher = None
        return False
    return True


def _prompt_stop_managed_services_if_any() -> None:
    """If this CLI started ngrok or a background connector, offer to stop them."""
    ngrok_live = _managed_ngrok_still_running()
    conn_live = _managed_connector_still_running()

    if not ngrok_live and not conn_live:
        return

    console.print()
    console.rule("[bold cyan]Background services[/bold cyan]", style="cyan")
    if ngrok_live:
        if Confirm.ask(
            "Stop the [bold]ngrok tunnel[/bold] that this CLI started?",
            default=True,
        ):
            _dispose_managed_ngrok_silent()
            console.print("[dim]ngrok stopped.[/dim]")
        else:
            console.print("[dim]Left ngrok running.[/dim]")
    if conn_live:
        if Confirm.ask(
            "Stop the [bold]connector[/bold] this CLI started in the background "
            "(Docker or python)?",
            default=True,
        ):
            _dispose_managed_connector_silent()
            console.print("[dim]Connector stopped.[/dim]")
        else:
            console.print("[dim]Left the connector running.[/dim]")
    console.print()


def _detect_region(project_dir: Path) -> str:
    """Read REGION from the connector's .env (matches run_dev.sh / template)."""
    env_path = project_dir / ".env"
    if env_path.exists():
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("REGION="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                return val if val else "besg"
    return "besg"


def _ngrok_local_api_tunnels() -> dict[str, Any] | None:
    """Return ngrok agent local API JSON, or None if unreachable."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:4040/api/tunnels",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def _port_from_upstream_addr(addr: str) -> int | None:
    """Parse local port from ngrok config.addr (e.g. http://127.0.0.1:2003)."""
    s = addr.strip()
    if not s or s.lower() in ("undefined", "none", "null"):
        return None
    m = re.search(r":(\d{1,5})\s*$", s)
    if m:
        p = int(m.group(1))
        return p if 1 <= p <= 65535 else None
    if s.isdigit():
        p = int(s)
        return p if 1 <= p <= 65535 else None
    return None


def _tunnel_local_port(tunnel: dict[str, Any]) -> int | None:
    """Return the upstream port this tunnel forwards to, or None if unknown / invalid."""
    conf = tunnel.get("config") or {}
    addr = conf.get("addr")
    if isinstance(addr, dict):
        p = addr.get("port")
        if p is not None:
            try:
                pi = int(p)
                return pi if 1 <= pi <= 65535 else None
            except (TypeError, ValueError):
                pass
        url = addr.get("URL") or addr.get("url")
        if isinstance(url, str):
            return _port_from_upstream_addr(url)
        return None
    if isinstance(addr, str):
        return _port_from_upstream_addr(addr)
    return None


def _tunnel_targets_port(tunnel: dict[str, Any], port: int) -> bool:
    return _tunnel_local_port(tunnel) == port


def _pick_https_public_url_for_port(tunnels_data: dict[str, Any], port: int) -> str | None:
    """Return the public HTTPS URL only for a tunnel whose upstream port matches *port*.

    Does not fall back to unrelated tunnels (avoids false positives when another
    broken tunnel exists with undefined upstream).
    """
    tunnels = tunnels_data.get("tunnels") or []
    for t in tunnels:
        if t.get("proto") == "https" and _tunnel_targets_port(t, port):
            url = t.get("public_url")
            if url:
                return str(url)
    for t in tunnels:
        if _tunnel_targets_port(t, port):
            url = t.get("public_url")
            if url:
                return str(url)
    return None


def _port_is_listening(port: int, host: str = "127.0.0.1") -> bool:
    """True if something accepts TCP connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout=0.75):
            return True
    except OSError:
        return False


def _wait_for_port(port: int, *, timeout: float, host: str = "127.0.0.1") -> bool:
    """Poll until the port accepts connections or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_is_listening(port, host=host):
            return True
        time.sleep(0.4)
    return False


def _start_main_py_background(project_dir: Path, main_py: Path) -> subprocess.Popen | None:
    try:
        return subprocess.Popen(
            [sys.executable, str(main_py)],
            cwd=str(project_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        console.print(f"[red]Could not start python main.py: {exc}[/red]")
        return None


def _start_connector_background(
    project_dir: Path, port: int
) -> tuple[bool, subprocess.Popen | None, bool]:
    """Start ./run_dev.sh (with a pseudo-TTY when needed) or python main.py in the background.

    Returns:
        (success, launcher_popen, docker_via_script) — *docker_via_script* is True when
        the launcher is ``script`` wrapping ``run_dev.sh`` (Docker), for cleanup via ``docker rm``.
    """
    run_dev = project_dir / "run_dev.sh"
    main_py = project_dir / "main.py"

    if run_dev.exists():
        script_bin = shutil.which("script")
        if script_bin and sys.platform != "win32":
            try:
                console.print(
                    "[dim]Launching [cyan]./run_dev.sh[/cyan] in the background "
                    "(Docker; first run may build for several minutes)…[/dim]"
                )
                if sys.platform == "darwin":
                    script_argv = [
                        script_bin, "-q", "/dev/null", "bash", str(run_dev),
                    ]
                else:
                    # util-linux `script`: -c runs a command with a pty
                    inner = f"bash {shlex.quote(str(run_dev.name))}"
                    script_argv = [
                        script_bin, "-q", "-c", inner, "/dev/null",
                    ]
                proc = subprocess.Popen(
                    script_argv,
                    cwd=str(project_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return True, proc, True
            except OSError as exc:
                console.print(f"[yellow]Could not start run_dev.sh via script: {exc}[/yellow]")

        if main_py.exists():
            console.print(
                "[yellow]Docker [bold]run_dev.sh[/bold] needs a pseudo-TTY for [bold]-it[/bold]. "
                "Starting [cyan]python main.py[/cyan] in the background instead.[/yellow]\n"
                "[dim]For full Docker dev, run [cyan]./run_dev.sh[/cyan] in a separate terminal.[/dim]"
            )
            py = _start_main_py_background(project_dir, main_py)
            return py is not None, py, False

        console.print(
            "[red]Cannot start the connector: [cyan]script[/cyan] is not available for headless "
            "[cyan]./run_dev.sh[/cyan], and [cyan]main.py[/cyan] is missing.[/red]"
        )
        return False, None, False

    if main_py.exists():
        console.print("[dim]Starting [cyan]python main.py[/cyan] in the background…[/dim]")
        py = _start_main_py_background(project_dir, main_py)
        return py is not None, py, False

    console.print(
        f"[red]No [cyan]run_dev.sh[/cyan] or [cyan]main.py[/cyan] in {project_dir}[/red]"
    )
    return False, None, False


def _ensure_connector_running_for_ngrok(project_dir: Path, port: int) -> bool:
    """Ensure localhost:*port* is serving the connector before exposing with ngrok."""
    global _managed_connector_launcher, _managed_connector_docker_script
    global _managed_connector_project_dir

    if _port_is_listening(port):
        console.print(
            f"[dim]Connector already listening on [cyan]localhost:{port}[/cyan].[/dim]"
        )
        return True

    console.print(
        "\n[bold]Starting the connector locally first[/bold] "
        "[dim](ngrok needs your app on this port).[/dim]"
    )
    ok, launcher, docker_script = _start_connector_background(project_dir, port)
    if not ok or launcher is None:
        return False

    _managed_connector_launcher = launcher
    _managed_connector_docker_script = docker_script
    _managed_connector_project_dir = project_dir

    console.print(
        f"[dim]Waiting for [cyan]localhost:{port}[/cyan] "
        f"(up to ~7 min on first Docker build)…[/dim]"
    )
    if not _wait_for_port(port, timeout=420.0):
        _dispose_managed_connector_silent()
        console.print(
            Panel(
                f"[red]Nothing accepted connections on port {port} in time.[/red]\n\n"
                "Start the connector manually:\n"
                f"  [cyan]cd {project_dir}[/cyan]\n"
                "  [cyan]./run_dev.sh[/cyan]   [dim]or[/dim]   [cyan]python main.py[/cyan]\n\n"
                "Then run **Expose with ngrok** again.",
                title="[red]Connector did not become ready[/red]",
                border_style="red",
            )
        )
        return False

    console.print(f"[green]Connector is reachable on port {port}.[/green]")
    return True


def _expose_with_ngrok(project_dir: Path, port: int) -> None:
    """Ensure ngrok is available; start a tunnel or reuse an existing one."""
    ngrok_bin = shutil.which("ngrok")
    if not ngrok_bin:
        console.print(Panel(
            "[bold]ngrok is not installed or not on your PATH.[/bold]\n\n"
            "  [bold]macOS (Homebrew):[/bold]\n"
            "    brew install ngrok/ngrok/ngrok\n\n"
            "  Or download the agent from the official site.\n"
            "  After installing, run [cyan]ngrok config add-authtoken <token>[/cyan] once.",
            title="[yellow]ngrok not found[/yellow]",
            border_style="yellow",
        ))
        if Confirm.ask("Open the ngrok download page?", default=True):
            webbrowser.open(_NGROK_DOWNLOAD_URL)
        return

    if not _ensure_connector_running_for_ngrok(project_dir, port):
        return

    region = _detect_region(project_dir)
    region_hint = (
        f"Use Stacksync region [bold]{region}[/bold] in Developer Studio and workflows."
    )

    data = _ngrok_local_api_tunnels()
    if data is not None:
        existing = _pick_https_public_url_for_port(data, port)
        if existing:
            console.print(
                f"\n[green]A tunnel to localhost:{port} is already running.[/green]\n"
                f"  Public URL: [bold cyan]{existing}[/bold cyan]\n"
            )
            console.print(f"[dim]{region_hint}[/dim]")
            return

    global _managed_ngrok_proc
    _dispose_managed_ngrok_silent()

    console.print(f"\n[bold]Starting ngrok[/bold] [dim](forwarding to localhost:{port})…[/dim]")
    try:
        proc = subprocess.Popen(
            [ngrok_bin, "http", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        console.print(f"[red]Could not start ngrok: {exc}[/red]")
        return

    deadline = time.monotonic() + 12.0
    public_url: str | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            console.print(
                Panel(
                    "[red]ngrok exited immediately.[/red]\n\n"
                    "Common causes: missing authtoken or port already in use.\n"
                    "  [cyan]ngrok config add-authtoken YOUR_TOKEN[/cyan]\n"
                    f"Or run [cyan]ngrok http {port}[/cyan] in a terminal to see the full error.",
                    title="[red]ngrok failed[/red]",
                    border_style="red",
                )
            )
            return
        tunnels = _ngrok_local_api_tunnels()
        if tunnels is not None:
            public_url = _pick_https_public_url_for_port(tunnels, port)
            if public_url:
                break
        time.sleep(0.35)

    if public_url:
        _managed_ngrok_proc = proc
        console.print(
            f"\n[green bold]Tunnel is up.[/green bold]\n"
            f"  Public URL: [bold cyan]{public_url}[/bold cyan]\n"
        )
        console.print(
            f"[dim]{region_hint} "
            f"Paste the URL into Developer Studio. "
            f"Inspect tunnels at http://127.0.0.1:4040[/dim]"
        )
    else:
        _managed_ngrok_proc = proc
        console.print(
            f"\n[yellow]ngrok was started in the background but the public URL could not "
            f"be read automatically.[/yellow]\n"
            f"  Open [cyan]http://127.0.0.1:4040[/cyan] in your browser to copy the HTTPS URL.\n"
        )


@click.group(invoke_without_command=True)
@click.version_option(package_name="workflows_cdk")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Stacksync Workflows CLI -- AI-assisted connector and module generation."""
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        _start_menu(ctx)


def _banner_once(ctx: click.Context) -> None:
    """Print the banner only once per CLI invocation."""
    state = ctx.ensure_object(dict)
    if not state.get("banner_shown"):
        _print_banner()
        state["banner_shown"] = True


def _pause_return_to_menu(*, label: str) -> None:
    """Wait for Enter so the user can read output before the menu redraws."""
    console.print()
    console.rule(f"[dim]Press Enter to return to the {label}[/dim]", style="dim")
    try:
        console.input()
    except (KeyboardInterrupt, EOFError):
        _prompt_stop_managed_services_if_any()
    console.print()


def _hint_path_instead_of_menu_number(choice: str, *, menu_range: str = "1–8") -> None:
    """If the user typed a path at the menu prompt, explain the flow."""
    s = choice.strip()
    if len(s) < 2:
        return
    if s.isdigit() and len(s) == 1:
        return
    pathish = (
        s.startswith((".", "/", "~"))
        or "/" in s
        or "\\" in s
        or s.endswith(("-connector", "_connector"))
    )
    if pathish:
        console.print(
            "[yellow]That looks like a path, not a menu number.[/yellow]\n"
            f"[dim]Pick an option from the menu ([cyan]{menu_range}[/cyan]) first.[/dim]"
        )


def _is_connector_root(path: Path) -> bool:
    """True if *path* looks like a connector root (has app_config.yaml)."""
    return (path / "app_config.yaml").is_file()


def _discover_connectors_near_cwd(*, max_results: int = 30) -> list[Path]:
    """List connector roots: current directory, then each immediate subfolder with app_config.yaml."""
    cwd = Path.cwd().resolve()
    ordered: list[Path] = []
    seen: set[Path] = set()

    def add(candidate: Path) -> None:
        rp = candidate.resolve()
        if rp in seen or not _is_connector_root(rp):
            return
        seen.add(rp)
        if len(ordered) < max_results:
            ordered.append(rp)

    add(cwd)
    try:
        for child in sorted(cwd.iterdir(), key=lambda p: p.name.lower()):
            if child.is_dir() and not child.name.startswith("."):
                add(child)
    except OSError:
        pass
    return ordered


def _connector_choice_label(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(Path.cwd().resolve())
        s = str(rel)
        return "." if s in (".", "") else s
    except ValueError:
        return str(path)


def _read_custom_connector_path() -> Path | None:
    raw = console.input(
        "[bold]Path to connector project[/bold] [dim](default: .)[/dim]\n> "
    ).strip() or "."
    project = Path(raw).expanduser().resolve()
    if not project.is_dir():
        console.print(f"[red]Not a directory:[/red] {project}")
        return None
    return project


def _prompt_connector_project_dir() -> Path | None:
    """Pick a connector from discovered folders, paste a path, or type a custom path."""
    discovered = _discover_connectors_near_cwd()

    if not discovered:
        console.print(
            "[dim]No app_config.yaml in . or immediate subfolders — enter path manually.[/dim]"
        )
        return _read_custom_connector_path()

    console.print()
    console.print(
        "[bold]Connector projects[/bold] "
        "[dim](current dir or subfolders with app_config.yaml)[/dim]"
    )
    for i, p in enumerate(discovered, start=1):
        console.print(f"  [cyan][{i}][/cyan]  {_connector_choice_label(p)}")
    console.print(f"  [cyan][c][/cyan]  Enter a custom path")

    if len(discovered) == 1:
        hint = "[bold]Select [cyan]1[/cyan] or [cyan]c[/cyan] [dim](Enter = 1)[/dim]:[/bold] "
    else:
        hint = (
            f"[bold]Select a number [cyan](1–{len(discovered)})[/cyan] "
            f"or [cyan]c[/cyan] [dim](Enter = 1)[/dim]:[/bold] "
        )
    sel = console.input(f"\n{hint}").strip()

    if not sel:
        return discovered[0]
    low = sel.lower()
    if low in ("c", "custom"):
        return _read_custom_connector_path()
    if sel.isdigit():
        n = int(sel)
        if 1 <= n <= len(discovered):
            return discovered[n - 1]
        console.print("[yellow]Invalid number.[/yellow]")
        return None

    project = Path(sel).expanduser().resolve()
    if project.is_dir():
        return project
    console.print(f"[red]Not a directory:[/red] {project}")
    return None


def _start_menu(ctx: click.Context) -> None:
    """Branded interactive menu when no subcommand is given."""
    _banner_once(ctx)
    while True:
        console.print(Panel(
            "  [bold cyan][1][/bold cyan]  Create a connector       "
            "[dim]Generate modules from a description[/dim]\n"
            "  [bold cyan][2][/bold cyan]  Update a connector       "
            "[dim]Add modules to an existing project[/dim]\n"
            "  [bold cyan][3][/bold cyan]  Validate a project        "
            "[dim]Pick connector or custom path[/dim]\n"
            "  [bold cyan][4][/bold cyan]  Run connector locally     "
            "[dim]Pick project, then run_dev.sh[/dim]\n"
            "  [bold cyan][5][/bold cyan]  Expose with ngrok         "
            "[dim]Pick project, then tunnel[/dim]\n"
            "  [bold cyan][6][/bold cyan]  View documentation        "
            "[dim]Open the Stacksync developer docs[/dim]\n"
            "  [bold cyan][7][/bold cyan]  Setup AI provider         "
            "[dim]Configure your Anthropic / OpenAI key[/dim]\n"
            "  [bold cyan][8][/bold cyan]  Exit",
            title="[bold]What would you like to do?[/bold]",
            border_style="cyan",
            padding=(1, 2),
        ))
        try:
            choice = console.input("[bold]Select [cyan][1-8][/cyan]:[/bold] ").strip()
        except (KeyboardInterrupt, EOFError):
            _prompt_stop_managed_services_if_any()
            return

        if choice == "8" or choice == "":
            _prompt_stop_managed_services_if_any()
            return

        try:
            if choice == "1":
                console.rule("[bold cyan]Create a connector[/bold cyan]", style="cyan")
                console.print()
                desc = console.input(
                    "[bold]Describe your connector:[/bold] "
                    "[dim](e.g. \"Klaviyo connector with API key\")[/dim]\n> "
                ).strip()
                if desc:
                    ctx.invoke(create, description=desc)
            elif choice == "2":
                console.rule("[bold cyan]Update a connector[/bold cyan]", style="cyan")
                console.print()
                proj_path = _prompt_connector_project_dir()
                if proj_path is None:
                    continue
                desc = console.input(
                    "[bold]What to add:[/bold] "
                    "[dim](e.g. \"add a delete_contact action\")[/dim]\n> "
                ).strip()
                if desc:
                    ctx.invoke(
                        create,
                        description=desc,
                        output=str(proj_path),
                        module_only=True,
                    )
                else:
                    console.print("[dim]No description provided.[/dim]")
            elif choice == "3":
                console.rule("[bold cyan]Validate a project[/bold cyan]", style="cyan")
                console.print()
                project = _prompt_connector_project_dir()
                if project is not None:
                    ctx.invoke(validate, path=str(project))
            elif choice == "4":
                console.rule("[bold cyan]Run connector locally[/bold cyan]", style="cyan")
                console.print()
                project = _prompt_connector_project_dir()
                if project is not None:
                    _run_connector(project)
            elif choice == "5":
                console.rule("[bold cyan]Expose with ngrok[/bold cyan]", style="cyan")
                console.print()
                project = _prompt_connector_project_dir()
                if project is not None:
                    port = detect_port(project)
                    _expose_with_ngrok(project, port)
            elif choice == "6":
                console.rule("[bold cyan]Documentation[/bold cyan]", style="cyan")
                console.print(f"[dim]Opening {_DOCS_URL} in your browser…[/dim]")
                webbrowser.open(_DOCS_URL)
                console.print("[green]Done.[/green]")
            elif choice == "7":
                console.rule("[bold cyan]Setup AI provider[/bold cyan]", style="cyan")
                console.print()
                ctx.invoke(setup)
            else:
                console.print(
                    "[yellow]Invalid choice.[/yellow] "
                    "[dim]Enter a number [cyan]1[/cyan]–[cyan]8[/cyan] "
                    "(see the list above).[/dim]"
                )
                _hint_path_instead_of_menu_number(choice, menu_range="1–8")
        except SystemExit:
            pass

        _pause_return_to_menu(label="main menu")


# ---------------------------------------------------------------------------
# workflows setup
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def setup(ctx: click.Context) -> None:
    """Configure your AI provider and API key."""
    _banner_once(ctx)
    _ensure_dotenv()
    _run_setup()


# ---------------------------------------------------------------------------
# workflows create
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("description")
@click.option(
    "-o", "--output",
    default=".",
    type=click.Path(file_okay=False),
    help="Parent directory for the generated project.",
)
@click.option("--dry-run", is_flag=True, help="Preview without writing files.")
@click.option(
    "--no-ai",
    is_flag=True,
    help="Use template matching only (no LLM call).",
)
@click.option(
    "--module-only",
    is_flag=True,
    help="Generate only module files into an existing connector project.",
)
@click.pass_context
def create(
    ctx: click.Context,
    description: str,
    output: str,
    dry_run: bool,
    no_ai: bool,
    module_only: bool,
) -> None:
    """Generate a Stacksync module or connector project from a natural-language description."""
    _banner_once(ctx)
    _ensure_dotenv()
    registry = CapabilityRegistry()

    spec: ConnectorSpec | None = None

    if no_ai:
        spec = _template_path(description, registry)
    else:
        if not _has_api_key():
            configured = _run_setup()
            if not configured:
                console.print("[yellow]No API key. Falling back to template matching.[/yellow]")
                spec = _template_path(description, registry)

        if spec is None:
            spec = _ai_path(description, registry)

    if spec is None:
        console.print(
            "[red]Could not generate a module spec from that description.[/red]\n"
            "Try being more specific, e.g.:\n"
            '  workflows create "Get LinkedIn posts using an API key"'
        )
        raise SystemExit(1)

    validation = validate_spec(spec, registry)
    if validation.warnings:
        for w in validation.warnings:
            console.print(f"[yellow]  warning:[/yellow] {w}")
    if not validation.ok:
        for e in validation.errors:
            console.print(f"[red]  error:[/red] {e}")
        console.print("\n[red]Spec has blocking errors. Aborting.[/red]")
        raise SystemExit(1)

    _show_preview(spec, module_only=module_only)

    if dry_run:
        console.print("\n[dim]--dry-run: no files written.[/dim]")
        return

    if not click.confirm("\nContinue?", default=True):
        console.print("[dim]Aborted.[/dim]")
        return

    output_dir = Path(output).resolve()

    version = _handle_overwrite(spec, output_dir, module_only)
    if version is None:
        return
    if version != spec.version:
        spec.version = version

    project_dir, _rationale = compile_connector(spec, output_dir, module_only=module_only)

    port = detect_port(project_dir)
    _show_post_gen(spec, project_dir, port, module_only=module_only)
    _interactive_menu(project_dir, port)


# ---------------------------------------------------------------------------
# workflows validate
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "-p", "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False),
    help="Path to a connector project directory.",
)
@click.pass_context
def validate(ctx: click.Context, path: str) -> None:
    """Validate a generated connector/module for Stacksync compatibility."""
    _banner_once(ctx)
    project = Path(path).resolve()
    console.print(f"\nValidating connector at [bold]{project}[/bold]...\n")

    ok = True
    app_cfg = project / "app_config.yaml"
    if app_cfg.exists():
        port = detect_port(project)
        console.print(f"  app_config.yaml: [green]OK[/green] (port: {port})")
    else:
        console.print("  app_config.yaml: [red]MISSING[/red]")
        ok = False

    modules_root = project / MODULES_DIR
    if not modules_root.is_dir():
        console.print(f"  {MODULES_DIR}/: [red]MISSING[/red]")
        ok = False
        return

    for module_dir in sorted(modules_root.iterdir()):
        if not module_dir.is_dir():
            continue
        for version_dir in sorted(module_dir.iterdir()):
            if not version_dir.is_dir():
                continue
            rel = version_dir.relative_to(project)
            console.print(f"  {rel}/:")

            cfg = version_dir / "module_config.yaml"
            if cfg.exists():
                console.print("    module_config.yaml: [green]OK[/green]")
            else:
                console.print("    module_config.yaml: [red]MISSING[/red]")
                ok = False

            schema_path = version_dir / "schema.json"
            if schema_path.exists():
                try:
                    schema = json.loads(schema_path.read_text())
                    ver = schema.get("metadata", {}).get("workflows_module_schema_version", "?")
                    n_fields = len(schema.get("fields", []))
                    console.print(f"    schema.json: [green]OK[/green] ({n_fields} fields, Module Schema v{ver})")
                except json.JSONDecodeError:
                    console.print("    schema.json: [red]INVALID JSON[/red]")
                    ok = False
            else:
                console.print("    schema.json: [red]MISSING[/red]")
                ok = False

            route = version_dir / "route.py"
            if route.exists():
                code = route.read_text()
                has_execute = bool(re.search(r'"/execute"', code))
                has_content = bool(re.search(r'"/content"', code))
                has_schema = bool(re.search(r'"/schema"', code))
                parts = ["/execute" if has_execute else "[red]/execute MISSING[/red]"]
                if has_content:
                    parts.append("/content")
                if has_schema:
                    parts.append("/schema")
                console.print(f"    route.py: [green]OK[/green] ({', '.join(parts)})")
                if not has_execute:
                    ok = False
            else:
                console.print("    route.py: [red]MISSING[/red]")
                ok = False

    console.print()
    if ok:
        console.print("[green bold]All checks passed.[/green bold]\n")
    else:
        console.print("[red bold]Some checks failed.[/red bold]\n")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# workflows list
# ---------------------------------------------------------------------------

@cli.command("list")
def list_capabilities() -> None:
    """List all known app capabilities in the registry."""
    registry = CapabilityRegistry()
    if not registry.slugs():
        console.print("[dim]No capabilities found.[/dim]")
        return

    table_lines: list[str] = []
    for slug in registry.slugs():
        m = registry.get(slug)
        if m is None:
            continue
        actions = ", ".join(m.action_names()) or "(none)"
        triggers = ", ".join(m.trigger_names()) or "(none)"
        table_lines.append(
            f"  [bold]{slug:12s}[/bold]  "
            f"actions: {actions}  |  triggers: {triggers}"
        )

    console.print(Panel(
        "\n".join(table_lines),
        title="[bold]Available capabilities[/bold]",
        border_style="blue",
    ))


# ---------------------------------------------------------------------------
# workflows inspect
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("app_slug")
def inspect(app_slug: str) -> None:
    """Show detailed capabilities for a specific app."""
    registry = CapabilityRegistry()
    manifest = registry.get(app_slug)
    if manifest is None:
        console.print(f"[red]Unknown app: '{app_slug}'[/red]")
        console.print(f"Available: {', '.join(registry.slugs())}")
        raise SystemExit(1)

    tree = Tree(f"[bold]{manifest.app.name}[/bold] ({manifest.app.slug})")
    tree.add(f"[dim]{manifest.app.description}[/dim]")
    tree.add(f"Auth: {manifest.app.auth.type}")

    if manifest.actions:
        actions_branch = tree.add("[bold]Actions[/bold]")
        for a in manifest.actions:
            fields = ", ".join(f.name for f in a.required_fields) or "(none)"
            actions_branch.add(f"{a.name} [{a.category}] -- {a.description}  (fields: {fields})")

    if manifest.triggers:
        triggers_branch = tree.add("[bold]Triggers[/bold]")
        for t in manifest.triggers:
            triggers_branch.add(f"{t.name} ({t.event}) -- {t.description}")

    console.print(tree)


# ---------------------------------------------------------------------------
# workflows guide
# ---------------------------------------------------------------------------

@cli.group()
def guide() -> None:
    """Step-by-step guidance for the Stacksync connector workflow."""


@guide.command("run")
def guide_run() -> None:
    """How to start the connector locally."""
    port = _detect_port_cwd()
    console.print(Panel(
        f"Starting your connector locally:\n\n"
        f"  1. cd <project-dir>\n"
        f"  2. pip install -r requirements.txt\n"
        f"  3. ./run_dev.sh\n\n"
        f"  Or without Docker:\n"
        f"     python main.py\n\n"
        f"  Your connector will start on port {port} "
        f"(configurable in app_config.yaml).",
        title="[bold]Run locally[/bold]",
        border_style="blue",
    ))


@guide.command("ngrok")
def guide_ngrok() -> None:
    """How to expose your connector with ngrok."""
    port = _detect_port_cwd()
    console.print(Panel(
        f"Exposing your connector with ngrok:\n\n"
        f"  Detected connector port: {port}\n\n"
        f"  1. Open a new terminal\n"
        f"  2. Run:\n"
        f"     ngrok http {port}\n"
        f"  3. Copy the public HTTPS URL\n"
        f"  4. Paste it in Developer Studio (see: workflows guide register)",
        title="[bold]ngrok setup[/bold]",
        border_style="blue",
    ))


@guide.command("register")
def guide_register() -> None:
    """How to register the connector in Developer Studio."""
    console.print(Panel(
        "Registering your connector in Stacksync Developer Studio:\n\n"
        "  1. Open Developer Studio in your browser\n"
        "  2. Create a new Custom Connector\n"
        "  3. Paste your ngrok URL as the connector base URL\n"
        "  4. Configure auth settings to match your connector\n"
        "  5. Save and activate the connector\n\n"
        "  Important: Your connector and workflows must be in the same region.",
        title="[bold]Register connector[/bold]",
        border_style="blue",
    ))


@guide.command("test")
def guide_test() -> None:
    """How to test your module in a Stacksync workflow."""
    console.print(Panel(
        "Testing your module in a Stacksync workflow:\n\n"
        "  1. Create a new workflow in Stacksync (same region as your connector)\n"
        "  2. Add a step using your custom connector\n"
        "  3. Select the action/module you generated\n"
        "  4. Fill in the form fields\n"
        "  5. Run the workflow and check the response\n\n"
        "  Tip: Check the connector logs in your terminal for debugging.",
        title="[bold]Test in workflow[/bold]",
        border_style="blue",
    ))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_port_cwd() -> int:
    """Try to read port from app_config.yaml in the current directory."""
    return detect_port(Path.cwd())


def _template_path(
    description: str,
    registry: CapabilityRegistry,
) -> ConnectorSpec | None:
    result = match_template(description)
    if result is not None:
        kw = ", ".join(result.matched_keywords)
        console.print(
            f"[green]Matched template '{result.template_name}' "
            f"(keywords: {kw})[/green]"
        )
        return result.spec
    return None


def _ai_path(
    description: str,
    registry: CapabilityRegistry,
) -> ConnectorSpec | None:
    try:
        from ..ai.planner import Planner, PlannerError
    except ImportError:
        console.print(
            "[yellow]AI planner unavailable (missing dependency). "
            "Falling back to template matching.[/yellow]"
        )
        return _template_path(description, registry)

    try:
        planner = Planner(registry)
    except (ImportError, PlannerError) as exc:
        console.print(f"[yellow]AI planner init failed: {exc}[/yellow]")
        console.print("[yellow]Falling back to template matching.[/yellow]")
        return _template_path(description, registry)
    except Exception:
        console.print_exception(max_frames=4)
        console.print("[yellow]Unexpected error initializing planner. Falling back to template matching.[/yellow]")
        return _template_path(description, registry)

    # Phase 1: parse intent and build prompt (instant)
    console.print("  [bold][1/3][/bold] Parsing intent…", end=" ")
    try:
        system, user_msg = planner.build_prompt(description)
    except Exception as exc:
        console.print("[red]failed[/red]")
        console.print(f"[yellow]{exc}[/yellow]")
        return _template_path(description, registry)
    console.print("[green]done[/green]")

    # Phase 2: call LLM (slow)
    t0 = time.monotonic()
    try:
        with console.status("  [bold][2/3][/bold] Calling AI provider…"):
            spec = planner.call_llm(system, user_msg)
    except PlannerError as exc:
        console.print(f"  [bold][2/3][/bold] Calling AI provider… [red]failed[/red]")
        console.print(f"[yellow]{exc}[/yellow]")
        console.print("[yellow]Falling back to template matching.[/yellow]")
        return _template_path(description, registry)
    except KeyboardInterrupt:
        console.print("\n[dim]Cancelled.[/dim]")
        return None
    except Exception:
        console.print(f"  [bold][2/3][/bold] Calling AI provider… [red]failed[/red]")
        console.print_exception(max_frames=6)
        console.print("[yellow]AI generation failed. Falling back to template matching.[/yellow]")
        return _template_path(description, registry)
    elapsed = time.monotonic() - t0
    console.print(f"  [bold][2/3][/bold] Calling AI provider… [green]done[/green] [dim]({elapsed:.0f}s)[/dim]")

    # Phase 3: validate (instant)
    console.print("  [bold][3/3][/bold] Validating spec…", end=" ")
    console.print("[green]done[/green]")

    if spec.needs_clarification:
        from ..ai.clarifier import render_clarification

        answers = render_clarification(spec)
        if answers:
            try:
                with console.status("  Refining with your answers…"):
                    spec = planner.refine(spec, answers)
            except PlannerError as exc:
                console.print(f"[yellow]Refinement failed: {exc}[/yellow]")
            except Exception:
                console.print_exception(max_frames=6)
                console.print("[yellow]Refinement failed, using initial spec.[/yellow]")

    return spec


def _show_preview(spec: ConnectorSpec, *, module_only: bool = False) -> None:
    """Compact preview: modules, fields summary, auth, endpoints."""
    lines: list[str] = []

    action_names = [a.name for a in spec.actions]
    trigger_names = [t.name for t in spec.triggers]
    module_summary = ", ".join(action_names + trigger_names)
    n_a, n_t = len(action_names), len(trigger_names)
    counts = []
    if n_a:
        counts.append(f"{n_a} action{'s' if n_a != 1 else ''}")
    if n_t:
        counts.append(f"{n_t} trigger{'s' if n_t != 1 else ''}")
    lines.append(f"[bold]Modules:[/bold] {module_summary} ({', '.join(counts)})")

    all_fields = []
    for a in spec.actions:
        all_fields.extend(a.required_fields)
        all_fields.extend(a.optional_fields)
    for t in spec.triggers:
        all_fields.extend(t.payload_fields)

    max_show = 8
    if all_fields:
        shown = all_fields[:max_show]
        field_names = ", ".join(f.name for f in shown)
        extra = f" (+{len(all_fields) - max_show} more)" if len(all_fields) > max_show else ""
        lines.append(f"[bold]Fields:[/bold]  {field_names}{extra}")

    auth_display = _AUTH_DISPLAY.get(spec.auth.type, spec.auth.type)
    lines.append(f"[bold]Auth:[/bold]    {auth_display}")

    endpoints = ["/execute"]
    if needs_content_endpoint(all_fields):
        endpoints.append("/content")
    if needs_schema_endpoint(all_fields):
        endpoints.append("/schema")
    lines.append(f"[bold]Endpoints:[/bold] {', '.join(endpoints)}")

    console.print(Panel(
        "\n".join(lines),
        title="[bold]Preview[/bold]",
        border_style="green",
    ))


def _handle_overwrite(
    spec: ConnectorSpec,
    output_dir: Path,
    module_only: bool,
) -> Optional[str]:
    """Check for existing module paths and handle overwrite/versioning.

    Returns the version string to use, or None to abort.
    """
    project_dir = output_dir if module_only else (output_dir / spec.directory_name)
    for a in spec.actions:
        target = project_dir / MODULES_DIR / a.name / spec.version
        if target.exists():
            return _prompt_overwrite(target, spec.version)
    for t in spec.triggers:
        target = project_dir / MODULES_DIR / t.name / spec.version
        if target.exists():
            return _prompt_overwrite(target, spec.version)
    return spec.version


def _prompt_overwrite(path: Path, current_version: str) -> Optional[str]:
    console.print(f"\n[yellow]A module already exists at {path}[/yellow]")
    choice = Prompt.ask(
        "Choose an option",
        choices=["abort", "overwrite", "new-version"],
        default="abort",
    )
    if choice == "abort":
        console.print("[dim]Aborted.[/dim]")
        return None
    if choice == "overwrite":
        return current_version
    num = int(current_version.lstrip("v")) + 1 if current_version.lstrip("v").isdigit() else 2
    return f"v{num}"


def _show_post_gen(
    spec: ConnectorSpec,
    project_dir: Path,
    port: int,
    *,
    module_only: bool = False,
) -> None:
    """Display post-generation summary and next steps."""
    files: list[str] = []
    for a in spec.actions:
        base = f"{MODULES_DIR}/{a.name}/{spec.version}"
        files.extend([f"{base}/module_config.yaml", f"{base}/schema.json", f"{base}/route.py"])
    for t in spec.triggers:
        base = f"{MODULES_DIR}/{t.name}/{spec.version}"
        files.extend([f"{base}/module_config.yaml", f"{base}/schema.json", f"{base}/route.py"])

    file_list = "\n".join(f"  {f}" for f in files)

    if module_only:
        region = _detect_region(project_dir)
        body = (
            f"[green bold]Module generated successfully[/green bold]\n\n"
            f"Files created:\n{file_list}\n\n"
            f"Next: restart your connector and test the new module "
            f"(Stacksync region: [bold]{region}[/bold])."
        )
    else:
        region = _detect_region(project_dir)
        body = (
            f"[green bold]Module generated successfully[/green bold]\n\n"
            f"Files created:\n{file_list}\n\n"
            f"[bold]Next steps:[/bold]\n"
            f"  1. Start the connector locally:\n"
            f"     ./run_dev.sh\n"
            f"  2. Expose your local backend:\n"
            f"     ngrok http {port}\n"
            f"  3. Copy the ngrok URL into Stacksync Developer Studio "
            f"(region: [bold]{region}[/bold])\n"
            f"  4. Create a workflow in the same region ([bold]{region}[/bold])\n"
            f"  5. Add your new action and test it"
        )

    console.print(Panel(body, border_style="green"))


def _interactive_menu(project_dir: Path, port: int) -> None:
    """Offer guided next-step actions after generation."""
    region = _detect_region(project_dir)
    while True:
        console.print(Panel(
            f"  [bold cyan][1][/bold cyan]  Run the connector        "
            f"[dim]Start locally via run_dev.sh[/dim]\n"
            f"  [bold cyan][2][/bold cyan]  Expose with ngrok         "
            f"[dim]run_dev.sh then ngrok http {port}[/dim]\n"
            f"  [bold cyan][3][/bold cyan]  Open documentation        "
            f"[dim]Stacksync developer docs[/dim]\n"
            f"  [bold cyan][4][/bold cyan]  Exit\n\n"
            f"  [dim]Stacksync region:[/dim] [bold]{region}[/bold]",
            title="[bold]What would you like to do next?[/bold]",
            border_style="cyan",
            padding=(1, 2),
        ))
        try:
            choice = console.input("[bold]Select [cyan][1-4][/cyan]:[/bold] ").strip()
        except (KeyboardInterrupt, EOFError):
            _prompt_stop_managed_services_if_any()
            return

        if choice == "4" or choice == "":
            _prompt_stop_managed_services_if_any()
            return

        if choice == "1":
            console.rule("[bold cyan]Run the connector[/bold cyan]", style="cyan")
            console.print()
            _run_connector(project_dir)
        elif choice == "2":
            console.rule("[bold cyan]Expose with ngrok[/bold cyan]", style="cyan")
            console.print()
            _expose_with_ngrok(project_dir, port)
        elif choice == "3":
            console.rule("[bold cyan]Documentation[/bold cyan]", style="cyan")
            console.print(f"[dim]Opening {_DOCS_URL} in your browser…[/dim]")
            webbrowser.open(_DOCS_URL)
            console.print("[green]Done.[/green]")
        else:
            console.print(
                "[yellow]Invalid choice.[/yellow] "
                "[dim]Enter [cyan]1[/cyan]–[cyan]4[/cyan].[/dim]"
            )
            _hint_path_instead_of_menu_number(choice, menu_range="1–4")

        _pause_return_to_menu(label="next steps menu")


def _run_connector(project_dir: Path) -> None:
    """Try to start the connector from *project_dir*."""
    run_dev = project_dir / "run_dev.sh"
    main_py = project_dir / "main.py"

    if run_dev.exists():
        console.print(f"\n[bold]Starting connector via run_dev.sh…[/bold]")
        console.print(
            "[dim]Press Ctrl+C to stop the connector. "
            "If this CLI started ngrok or a background connector earlier, "
            "you will be asked whether to stop those next.[/dim]\n"
        )
        try:
            subprocess.run(["bash", str(run_dev)], cwd=str(project_dir))
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        _prompt_stop_managed_services_if_any()
    elif main_py.exists():
        console.print(f"\n[bold]Starting connector via python main.py…[/bold]")
        console.print(
            "[dim]Press Ctrl+C to stop the connector. "
            "If this CLI started ngrok or a background connector earlier, "
            "you will be asked whether to stop those next.[/dim]\n"
        )
        try:
            subprocess.run(["python", str(main_py)], cwd=str(project_dir))
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        _prompt_stop_managed_services_if_any()
    else:
        console.print(
            f"\n[yellow]No run_dev.sh or main.py found in {project_dir}.[/yellow]\n"
            f"  cd {project_dir}\n"
            f"  pip install -r requirements.txt\n"
            f"  python main.py"
        )
