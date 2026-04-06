"""
One-shot clarification engine.

Takes the ``ambiguities`` list from a ConnectorSpec, renders them as
individual prompts, collects the user's answers, and returns a plain-text
string that can be fed back into the LLM refinement prompt.
"""

from __future__ import annotations

from rich.console import Console
from rich.prompt import Prompt

from ..spec.connector_spec import AmbiguitySpec, ConnectorSpec

console = Console()


def render_clarification(spec: ConnectorSpec) -> str:
    """Display ambiguities one at a time and collect answers interactively.

    Returns a plain-text summary of the user's choices, ready to be passed
    to ``Planner.refine()``.
    """
    ambiguities = spec.ambiguities
    if not ambiguities:
        return ""

    ambiguities = ambiguities[:3]
    count = len(ambiguities)

    console.print(
        f"\n[bold]I need {count} detail{'s' if count != 1 else ''} "
        f"before generating:[/bold]"
    )

    answers: list[str] = []
    for idx, amb in enumerate(ambiguities, 1):
        console.print(f"\n[bold cyan]({idx}/{count})[/bold cyan] {amb.question}")

        options = amb.options or []
        default = amb.default or (options[0] if options else None)

        if options:
            for i, opt in enumerate(options, 1):
                marker = "[bold green]*[/bold green] " if opt == default else "  "
                console.print(f"  {marker}{i}. {opt}")
            console.print(f"  [dim]Press Enter for default: {default}[/dim]")

            raw = console.input("[bold]> [/bold]").strip()
            if not raw:
                chosen = default
            elif raw.isdigit() and 1 <= int(raw) <= len(options):
                chosen = options[int(raw) - 1]
            else:
                chosen = raw
        else:
            raw = console.input(f"[bold]> [/bold][dim]({default})[/dim] ").strip()
            chosen = raw if raw else default

        answers.append(f"{amb.question}: {chosen}")

    return "\n".join(answers)
