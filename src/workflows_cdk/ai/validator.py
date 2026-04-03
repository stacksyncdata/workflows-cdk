"""
Deterministic post-LLM validator.

Runs *after* the planner produces a ConnectorSpec and checks it against the
capability registry.  Returns blocking errors and non-blocking warnings so
the CLI can decide whether to proceed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..registry.registry import CapabilityRegistry
from ..spec.connector_spec import ConnectorSpec

_VALID_FIELD_TYPES = frozenset({"string", "number", "boolean", "object", "array"})
_VALID_AUTH_TYPES = frozenset({"oauth2", "api_key", "basic", "none"})
_VALID_CATEGORIES = frozenset({"action", "trigger", "search", "transform"})


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def validate_spec(spec: ConnectorSpec, registry: CapabilityRegistry) -> ValidationResult:
    """Validate a ConnectorSpec against the registry.  Pure, no side-effects."""
    result = ValidationResult()

    if not spec.app_type:
        result.errors.append("app_type is empty")
    if not spec.app_name:
        result.errors.append("app_name is empty")

    _validate_auth(spec, result)
    _validate_actions(spec, registry, result)
    _validate_triggers(spec, registry, result)
    _validate_no_route_collisions(spec, result)

    return result


def _validate_auth(spec: ConnectorSpec, result: ValidationResult) -> None:
    if spec.auth.type not in _VALID_AUTH_TYPES:
        result.errors.append(
            f"Unknown auth type '{spec.auth.type}'. "
            f"Valid: {', '.join(sorted(_VALID_AUTH_TYPES))}"
        )


def _validate_actions(
    spec: ConnectorSpec,
    registry: CapabilityRegistry,
    result: ValidationResult,
) -> None:
    manifest = registry.get(spec.app_type)
    seen_names: set[str] = set()

    for action in spec.actions:
        if action.name in seen_names:
            result.errors.append(f"Duplicate action name: '{action.name}'")
        seen_names.add(action.name)

        if action.category not in _VALID_CATEGORIES:
            result.errors.append(
                f"Action '{action.name}' has invalid category '{action.category}'"
            )

        for f in action.required_fields + action.optional_fields:
            if f.type not in _VALID_FIELD_TYPES:
                result.warnings.append(
                    f"Action '{action.name}', field '{f.name}': "
                    f"unknown type '{f.type}', defaulting to 'string'"
                )

        if manifest is not None:
            known_actions = manifest.action_names()
            if action.name not in known_actions:
                result.warnings.append(
                    f"Action '{action.name}' is not in the {spec.app_type} "
                    f"capability manifest (known: {', '.join(known_actions)})"
                )

    if manifest is None and spec.app_type:
        result.warnings.append(
            f"App '{spec.app_type}' is not in the built-in registry. "
            f"The generated connector will work but fields/auth are unverified."
        )


def _validate_triggers(
    spec: ConnectorSpec,
    registry: CapabilityRegistry,
    result: ValidationResult,
) -> None:
    manifest = registry.get(spec.app_type)
    seen_names: set[str] = set()

    for trigger in spec.triggers:
        if trigger.name in seen_names:
            result.errors.append(f"Duplicate trigger name: '{trigger.name}'")
        seen_names.add(trigger.name)

        if manifest is not None:
            known_triggers = manifest.trigger_names()
            if trigger.name not in known_triggers:
                result.warnings.append(
                    f"Trigger '{trigger.name}' is not in the {spec.app_type} "
                    f"capability manifest (known: {', '.join(known_triggers)})"
                )


def _validate_no_route_collisions(
    spec: ConnectorSpec,
    result: ValidationResult,
) -> None:
    paths: set[str] = set()
    for action in spec.actions:
        path = f"/{action.name}/{spec.version}/execute"
        if path in paths:
            result.errors.append(f"Route collision: {path}")
        paths.add(path)

    for trigger in spec.triggers:
        path = f"/{trigger.name}/{spec.version}/execute"
        if path in paths:
            result.errors.append(f"Route collision: {path}")
        paths.add(path)
