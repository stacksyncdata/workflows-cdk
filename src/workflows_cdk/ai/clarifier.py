"""
One-shot clarification engine.

Takes the ``ambiguities`` list from a ConnectorSpec, renders them as a single
compact terminal prompt, collects the user's answers, and returns a plain-text
string that can be fed back into the LLM refinement prompt.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ..spec.connector_spec import AmbiguitySpec, ConnectorSpec

console = Console()


def render_clarification(spec: ConnectorSpec) -> str:
    """Display ambiguities and collect answers interactively.

    Returns a plain-text summary of the user's choices, ready to be passed
    to ``Planner.refine()``.
    """
    ambiguities = spec.ambiguities
    if not ambiguities:
        return ""

    action_count = len(spec.actions)
    trigger_count = len(spec.triggers)

    parts = []
    if action_count:
        parts.append(f"{action_count} action{'s' if action_count != 1 else ''}")
    if trigger_count:
        parts.append(f"{trigger_count} trigger{'s' if trigger_count != 1 else ''}")
    summary = " + ".join(parts) if parts else "a connector"

    header = (
        f"I can build this {spec.app_name} with {summary}.\n"
        f"I need {len(ambiguities)} detail{'s' if len(ambiguities) != 1 else ''} "
        f"before scaffolding:"
    )

    body_lines: list[str] = []
    for idx, amb in enumerate(ambiguities, 1):
        options_str = _format_options(amb)
        body_lines.append(f"  {idx}. {amb.question}: {options_str}")

    body = "\n".join(body_lines)

    console.print()
    console.print(Panel(
        f"{header}\n\n{body}",
        title="[bold]Clarification needed[/bold]",
        border_style="yellow",
    ))

    console.print(
        "\n[dim]Press Enter to accept defaults (shown in brackets).[/dim]"
    )
    raw = console.input("[bold]Your answers:[/bold] ").strip()

    if not raw:
        return _defaults_summary(ambiguities)

    return _merge_answers(ambiguities, raw)


def _format_options(amb: AmbiguitySpec) -> str:
    if not amb.options:
        return f"[{amb.default or '?'}]"

    parts: list[str] = []
    for opt in amb.options:
        if opt == amb.default:
            parts.append(f"[{opt}]")
        else:
            parts.append(opt)
    return " / ".join(parts)


def _defaults_summary(ambiguities: list[AmbiguitySpec]) -> str:
    lines: list[str] = []
    for amb in ambiguities:
        default = amb.default or (amb.options[0] if amb.options else "unspecified")
        lines.append(f"{amb.question}: {default}")
    return "\n".join(lines)


def _merge_answers(ambiguities: list[AmbiguitySpec], raw: str) -> str:
    """Best-effort parse of comma-separated or numbered answers."""
    tokens = [t.strip() for t in raw.replace(";", ",").split(",")]

    lines: list[str] = []
    for idx, amb in enumerate(ambiguities):
        if idx < len(tokens) and tokens[idx]:
            lines.append(f"{amb.question}: {tokens[idx]}")
        else:
            default = amb.default or (amb.options[0] if amb.options else "unspecified")
            lines.append(f"{amb.question}: {default}")
    return "\n".join(lines)
