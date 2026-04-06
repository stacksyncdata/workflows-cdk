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
    _validate_stacksync_contracts(spec, result)

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

        # Registry hints help the LLM but are not a gate for validation.


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

        # Registry hints help the LLM but are not a gate for validation.


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


def _validate_stacksync_contracts(
    spec: ConnectorSpec,
    result: ValidationResult,
) -> None:
    """Stacksync-specific checks that go beyond generic type/name validation."""
    if spec.auth.type in ("oauth2", "api_key") and not spec.app_type:
        result.errors.append(
            "Auth requires a connection but app_type is empty "
            "(needed for allowed_app_types in schema)"
        )

    for action in spec.actions:
        all_fields = list(action.required_fields) + list(action.optional_fields)
        _check_field_contracts(action.name, all_fields, result)

    for trigger in spec.triggers:
        _check_field_contracts(trigger.name, list(trigger.payload_fields), result)


def _check_field_contracts(
    module_name: str,
    fields: list,
    result: ValidationResult,
) -> None:
    all_ids = {f.name for f in fields}

    for f in fields:
        if f.depends_on and f.depends_on not in all_ids:
            result.errors.append(
                f"Module '{module_name}', field '{f.name}': "
                f"depends_on='{f.depends_on}' references non-existent field"
            )

        if f.type == "object" and not f.choices and not f.dynamic_content:
            result.warnings.append(
                f"Module '{module_name}', field '{f.name}': "
                f"type 'object' typically needs choices or dynamic_content"
            )
