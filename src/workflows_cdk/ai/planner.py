"""
Planner orchestrator — the single entry point for AI-powered connector creation.

Flow:
  1. Parse intent from user description (extract slugs, verbs)
  2. Build the LLM prompt with relevant capability manifests
  3. Call the configured LLM provider with structured output
  4. Return a validated ConnectorSpec (the CLI handles clarification / compilation)

Provider selection (Anthropic preferred):
  - Set ``ANTHROPIC_API_KEY`` to use Claude  (default model: claude-sonnet-4-6)
  - Set ``OPENAI_API_KEY``   to use OpenAI  (default model: gpt-5-nano)
  - If both are set, Anthropic wins unless ``WORKFLOWS_AI_PROVIDER=openai``

Structured output:
  - OpenAI    → Responses API with ``text.format`` json_schema (strict)
  - Anthropic → ``output_config.format`` json_schema (SDK auto-transforms)
  Both guarantee schema-compliant JSON — no post-hoc parsing needed.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Literal

from ..registry.registry import CapabilityRegistry
from ..spec.connector_spec import ConnectorSpec
from .intent_parser import parse_intent
from .prompts import PLANNER_SYSTEM_PROMPT, REFINEMENT_PROMPT

logger = logging.getLogger(__name__)

Provider = Literal["openai", "anthropic"]

DEFAULT_OPENAI_MODEL = "gpt-5-nano"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"


class PlannerError(Exception):
    pass


# ---------------------------------------------------------------------------
# Provider detection (Anthropic default)
# ---------------------------------------------------------------------------

def _detect_provider() -> Provider:
    explicit = os.environ.get("WORKFLOWS_AI_PROVIDER", "").lower()
    if explicit in ("openai", "anthropic"):
        return explicit  # type: ignore[return-value]

    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"

    raise PlannerError(
        "No AI provider configured.  "
        "Set ANTHROPIC_API_KEY or OPENAI_API_KEY, "
        "or pass --no-ai to use template matching instead."
    )


# ---------------------------------------------------------------------------
# JSON Schema from Pydantic
# ---------------------------------------------------------------------------

def _build_json_schema() -> dict[str, Any]:
    """Generate a JSON Schema from ConnectorSpec with ``additionalProperties:
    false`` on all objects and all properties promoted to ``required``.

    Both OpenAI and Anthropic require this for their structured-output modes.
    """
    schema = ConnectorSpec.model_json_schema()
    _prepare_strict(schema)
    return schema


_PYDANTIC_ONLY_KEYWORDS = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern", "minItems", "maxItems",
    "uniqueItems",
}


def _prepare_strict(node: dict[str, Any]) -> None:
    """Recursively add ``additionalProperties: false``, promote all properties
    to ``required``, and strip Pydantic validation keywords that neither
    provider supports in structured-output schemas.  The constraints are still
    enforced by ``ConnectorSpec.model_validate()`` after parsing."""
    for kw in _PYDANTIC_ONLY_KEYWORDS:
        node.pop(kw, None)

    if node.get("type") == "object":
        node["additionalProperties"] = False
        if "properties" in node:
            node.setdefault("required", list(node["properties"].keys()))

    for key in ("properties", "$defs"):
        container = node.get(key)
        if isinstance(container, dict):
            for v in container.values():
                if isinstance(v, dict):
                    _prepare_strict(v)

    items = node.get("items")
    if isinstance(items, dict):
        _prepare_strict(items)

    for combo_key in ("anyOf", "oneOf", "allOf"):
        combo = node.get(combo_key)
        if isinstance(combo, list):
            for item in combo:
                if isinstance(item, dict):
                    _prepare_strict(item)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class Planner:
    """Stateless orchestrator: description in, ConnectorSpec out."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def build_prompt(self, description: str) -> tuple[str, str]:
        """Phase 1: parse intent and build the system prompt (instant).

        Returns (system_prompt, user_message).
        """
        intent = parse_intent(description, self.registry)

        if intent.detected_slugs:
            summaries = [
                self.registry.get(slug).summary_for_llm()
                for slug in intent.detected_slugs
                if self.registry.get(slug) is not None
            ]
        else:
            summaries = self.registry.summaries_for_llm()

        capabilities_json = json.dumps(summaries or self.registry.summaries_for_llm(), indent=2)
        system = PLANNER_SYSTEM_PROMPT.format(
            capabilities_json=capabilities_json,
        )
        return system, description

    def call_llm(self, system: str, user: str) -> ConnectorSpec:
        """Phase 2: call the LLM and parse the spec (slow)."""
        raw = _call_llm(system=system, user=user)
        return _parse_spec(raw)

    def plan(self, description: str) -> ConnectorSpec:
        system, user = self.build_prompt(description)
        return self.call_llm(system, user)

    def refine(self, draft: ConnectorSpec, user_answers: str) -> ConnectorSpec:
        system = REFINEMENT_PROMPT.format(
            draft_spec_json=draft.model_dump_json(indent=2),
            user_answers=user_answers,
        )
        raw = _call_llm(system=system, user=user_answers)
        return _parse_spec(raw)


# ---------------------------------------------------------------------------
# LLM dispatch
# ---------------------------------------------------------------------------

def _call_llm(*, system: str, user: str) -> str:
    provider = _detect_provider()
    if provider == "anthropic":
        return _call_anthropic(system=system, user=user)
    return _call_openai(system=system, user=user)


# ---------------------------------------------------------------------------
# Anthropic / Claude  — output_config.format json_schema
# ---------------------------------------------------------------------------

def _call_anthropic(*, system: str, user: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise PlannerError(
            "The 'anthropic' package is required for Claude.  "
            "Install it with:  pip install workflows-cdk"
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise PlannerError("ANTHROPIC_API_KEY environment variable is not set.")

    client = anthropic.Anthropic(api_key=api_key, timeout=120.0)
    model = os.environ.get("WORKFLOWS_AI_MODEL", DEFAULT_ANTHROPIC_MODEL)

    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=8192,
                system=system,
                messages=[{"role": "user", "content": user}],
                temperature=0.2,
            )
            break
        except Exception as exc:
            last_exc = exc
            if attempt == 0 and "connection" in str(exc).lower():
                logger.debug("Anthropic connection error, retrying in 2s…")
                time.sleep(2)
                continue
            raise PlannerError(f"Anthropic API error: {exc}") from exc
    else:
        raise PlannerError(f"Anthropic API error: {last_exc}") from last_exc

    text_blocks = [b.text for b in resp.content if b.type == "text"]
    if not text_blocks:
        raise PlannerError("Claude returned empty response")
    return text_blocks[0]


# ---------------------------------------------------------------------------
# OpenAI  — Responses API with json_schema structured output
# ---------------------------------------------------------------------------

def _call_openai(*, system: str, user: str) -> str:
    try:
        import openai
    except ImportError:
        raise PlannerError(
            "The 'openai' package is required for AI planning.  "
            "Install it with:  pip install workflows-cdk"
        )

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise PlannerError("OPENAI_API_KEY environment variable is not set.")

    client = openai.OpenAI(api_key=api_key)
    model = os.environ.get("WORKFLOWS_AI_MODEL", DEFAULT_OPENAI_MODEL)
    schema = _build_json_schema()

    try:
        resp = client.responses.create(
            model=model,
            instructions=system,
            input=user,
            text={
                "format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "connector_spec",
                        "schema": schema,
                        "strict": True,
                    },
                },
            },
            temperature=0.2,
        )
        return resp.output_text
    except Exception as exc:
        logger.debug("Responses API unavailable (%s), falling back to chat completions", exc)

    try:
        return _chat_completions_fallback(client, model, system, user, schema)
    except Exception as exc:
        raise PlannerError(f"OpenAI API error: {exc}") from exc


def _chat_completions_fallback(
    client: "openai.OpenAI",
    model: str,
    system: str,
    user: str,
    schema: dict[str, Any],
) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "connector_spec",
                "schema": schema,
                "strict": True,
            },
        },
        temperature=0.2,
    )
    content = resp.choices[0].message.content
    if content is None:
        raise PlannerError("LLM returned empty response")
    return content


# ---------------------------------------------------------------------------
# Spec parsing
# ---------------------------------------------------------------------------

def _parse_spec(raw: str) -> ConnectorSpec:
    """Parse LLM output into a ConnectorSpec.

    With structured output the JSON is already valid, but we keep the
    fence-stripping as a safety net for fallback paths.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlannerError(f"LLM returned invalid JSON: {exc}\n\nRaw output:\n{raw}")

    return ConnectorSpec.model_validate(data)
