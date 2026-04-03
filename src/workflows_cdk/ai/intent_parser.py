"""
Lightweight pre-processing of the user prompt *before* calling the LLM.

Extracts candidate app slugs and action verbs so the planner can narrow
which capability manifests to inject into the system prompt context window.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..registry.registry import CapabilityRegistry

_TRIGGER_VERBS = frozenset({
    "when", "on", "listen", "react", "trigger", "watch", "monitor",
})

_SEARCH_VERBS = frozenset({
    "list", "search", "find", "get", "fetch", "query", "lookup",
})


@dataclass
class ParsedIntent:
    raw: str
    detected_slugs: list[str] = field(default_factory=list)
    has_trigger_intent: bool = False
    has_search_intent: bool = False
    tokens: list[str] = field(default_factory=list)


def parse_intent(description: str, registry: CapabilityRegistry) -> ParsedIntent:
    """Extract structured signals from the raw user prompt."""
    tokens = description.lower().split()
    token_set = set(tokens)

    detected_slugs: list[str] = []
    for slug in registry.slugs():
        manifest = registry.get(slug)
        if manifest is None:
            continue
        name_lower = manifest.app.name.lower()
        if slug in token_set or name_lower in description.lower():
            detected_slugs.append(slug)

    return ParsedIntent(
        raw=description,
        detected_slugs=detected_slugs,
        has_trigger_intent=bool(token_set & _TRIGGER_VERBS),
        has_search_intent=bool(token_set & _SEARCH_VERBS),
        tokens=tokens,
    )
