"""
CLI entry point: ``workflows create "Slack connector: send messages, list channels"``

Registered as a console_script in setup.py so ``pip install workflows-cdk``
makes the ``workflows`` command available globally.
"""

from __future__ import annotations

import os
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.tree import Tree

load_dotenv()

from ..ai.validator import validate_spec
from ..registry.registry import CapabilityRegistry
from ..spec.compiler import compile_connector, preview_tree
from ..spec.connector_spec import ConnectorSpec
from ..templates.matcher import match_template

console = Console()

ENV_FILE = Path.cwd() / ".env"


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

    console.print(f"\n[green bold]Done![/green bold] {key_name} saved to [cyan]{ENV_FILE}[/cyan]")
    console.print("[dim]You can also export it in your shell or edit .env directly.[/dim]\n")
    return True


def _save_to_env(key_name: str, value: str) -> None:
    """Append or update a key in the .env file."""
    lines: list[str] = []
    found = False

    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            stripped = line.lstrip("# ").split("=", 1)[0].strip()
            if stripped == key_name:
                lines.append(f"{key_name}={value}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{key_name}={value}")

    ENV_FILE.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="workflows_cdk")
def cli() -> None:
    """Stacksync Workflows CLI -- create connectors in one command."""


# ---------------------------------------------------------------------------
# workflows setup
# ---------------------------------------------------------------------------

@cli.command()
def setup() -> None:
    """Configure your AI provider and API key."""
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
def create(description: str, output: str, dry_run: bool, no_ai: bool) -> None:
    """Create a connector from a natural-language description (max ~30 words)."""
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
            "[red]Could not generate a connector spec from that description.[/red]\n"
            "Try being more specific, e.g.:\n"
            '  workflows create "Slack connector: send messages, list channels"'
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

    _show_preview(spec)

    if dry_run:
        console.print("\n[dim]--dry-run: no files written.[/dim]")
        return

    output_dir = Path(output).resolve()
    project_dir = compile_connector(spec, output_dir)
    console.print(f"\n[green bold]Connector created at:[/green bold] {project_dir}")
    console.print("[dim]Run it with:[/dim]  cd {0} && pip install -r requirements.txt && python main.py".format(
        project_dir.name
    ))


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
# Internal paths
# ---------------------------------------------------------------------------

def _template_path(
    description: str,
    registry: CapabilityRegistry,
) -> ConnectorSpec | None:
    spec = match_template(description)
    if spec is not None:
        console.print("[green]Matched a built-in template.[/green]")
    return spec


def _ai_path(
    description: str,
    registry: CapabilityRegistry,
) -> ConnectorSpec | None:
    try:
        from ..ai.planner import Planner, PlannerError
    except Exception:
        console.print(
            "[yellow]AI planner unavailable. Falling back to template matching.[/yellow]"
        )
        return _template_path(description, registry)

    try:
        planner = Planner(registry)
    except Exception:
        console.print(
            "[yellow]AI planner init failed. Falling back to template matching.[/yellow]"
        )
        return _template_path(description, registry)

    try:
        with console.status("[bold]Planning connector...[/bold]"):
            spec = planner.plan(description)
    except PlannerError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        console.print("[yellow]Falling back to template matching.[/yellow]")
        return _template_path(description, registry)

    if spec.needs_clarification:
        from ..ai.clarifier import render_clarification

        answers = render_clarification(spec)
        if answers:
            with console.status("[bold]Refining spec...[/bold]"):
                spec = planner.refine(spec, answers)

    return spec


def _show_preview(spec: ConnectorSpec) -> None:
    tree_text = preview_tree(spec)

    action_names = ", ".join(a.name for a in spec.actions) or "(none)"
    trigger_names = ", ".join(t.name for t in spec.triggers) or "(none)"

    info = (
        f"[bold]{spec.app_name}[/bold]  (type: {spec.app_type}, auth: {spec.auth.type})\n"
        f"Actions:  {action_names}\n"
        f"Triggers: {trigger_names}\n\n"
        f"[dim]{tree_text}[/dim]"
    )
    console.print(Panel(info, title="[bold]Preview[/bold]", border_style="green"))
