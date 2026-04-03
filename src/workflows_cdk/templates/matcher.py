"""
Template matcher -- resolves a user description to a pre-built ConnectorSpec
without calling any LLM.  Used as the ``--no-ai`` fast path and as a fallback
when the OpenAI key is not configured.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from ..spec.connector_spec import (
    ActionSpec,
    AuthSpec,
    ConnectorSpec,
    FieldSpec,
    TriggerSpec,
)

logger = logging.getLogger(__name__)

_LIBRARY_DIR = Path(__file__).parent / "library"


class _Template:
    """Internal wrapper around a single template YAML file."""

    def __init__(self, data: dict, path: Path) -> None:
        self.data = data
        self.path = path
        self.keywords: list[str] = [
            k.lower() for k in data.get("keywords", [])
        ]
        self.slug: str = data.get("app_type", path.stem)

    def score(self, query_tokens: set[str]) -> int:
        corpus = set(self.keywords) | {self.slug}
        return len(query_tokens & corpus)

    def to_connector_spec(self) -> ConnectorSpec:
        d = self.data
        auth_raw = d.get("auth", {})
        return ConnectorSpec(
            app_type=d["app_type"],
            app_name=d["app_name"],
            version=d.get("version", "v1"),
            actions=[_parse_action(a) for a in d.get("actions", [])],
            triggers=[_parse_trigger(t) for t in d.get("triggers", [])],
            auth=AuthSpec(
                type=auth_raw.get("type", "oauth2"),
                scopes=auth_raw.get("scopes", []),
            ),
            confidence=1.0,
        )


def _parse_field(raw: dict) -> FieldSpec:
    return FieldSpec(
        name=raw["name"],
        type=raw.get("type", "string"),
        description=raw.get("description", ""),
    )


def _parse_action(raw: dict) -> ActionSpec:
    return ActionSpec(
        name=raw["name"],
        category=raw.get("category", "action"),
        description=raw.get("description", ""),
        required_fields=[_parse_field(f) for f in raw.get("required_fields", [])],
        optional_fields=[_parse_field(f) for f in raw.get("optional_fields", [])],
    )


def _parse_trigger(raw: dict) -> TriggerSpec:
    return TriggerSpec(
        name=raw["name"],
        event=raw.get("event", ""),
        description=raw.get("description", ""),
        payload_fields=[_parse_field(f) for f in raw.get("payload_fields", [])],
    )


def _load_templates() -> list[_Template]:
    templates: list[_Template] = []
    if not _LIBRARY_DIR.is_dir():
        return templates
    for path in sorted(_LIBRARY_DIR.glob("*.yaml")):
        try:
            with open(path) as fh:
                data = yaml.safe_load(fh) or {}
            templates.append(_Template(data, path))
        except Exception:
            logger.warning("Failed to load template %s", path, exc_info=True)
    return templates


def match_template(description: str) -> Optional[ConnectorSpec]:
    """Return the best-matching template as a ``ConnectorSpec``, or *None*."""
    tokens = set(description.lower().split())
    templates = _load_templates()
    if not templates:
        return None

    best: Optional[_Template] = None
    best_score = 0
    for tpl in templates:
        s = tpl.score(tokens)
        if s > best_score:
            best_score = s
            best = tpl

    if best is None or best_score == 0:
        return None

    return best.to_connector_spec()
