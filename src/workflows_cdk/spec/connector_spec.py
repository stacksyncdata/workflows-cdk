"""
Intermediate connector specification format.

The LLM planner produces a ConnectorSpec; the deterministic validator checks it;
the compiler turns it into a scaffolded CDK project on disk.  No component
downstream of the planner ever sees raw LLM text -- only this typed model.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class FieldSpec(BaseModel):
    name: str
    type: Literal["string", "number", "boolean", "object", "array"] = "string"
    description: str = ""
    required: bool = True


class AuthSpec(BaseModel):
    type: Literal["oauth2", "api_key", "basic", "none"] = "oauth2"
    scopes: list[str] = Field(default_factory=list)
    fields: list[FieldSpec] = Field(default_factory=list)


class ActionSpec(BaseModel):
    name: str
    category: Literal["action", "trigger", "search", "transform"] = "action"
    description: str = ""
    required_fields: list[FieldSpec] = Field(default_factory=list)
    optional_fields: list[FieldSpec] = Field(default_factory=list)
    implementation: str = Field(
        default="",
        description="Python code for the /execute endpoint body (after data extraction)",
    )


class TriggerSpec(BaseModel):
    name: str
    event: str = ""
    description: str = ""
    payload_fields: list[FieldSpec] = Field(default_factory=list)
    implementation: str = Field(
        default="",
        description="Python code for the /execute endpoint body (polling/webhook logic)",
    )


class AmbiguitySpec(BaseModel):
    """A single point the planner could not resolve from the prompt alone."""

    question: str
    options: list[str] = Field(default_factory=list)
    default: Optional[str] = None


class ConnectorSpec(BaseModel):
    """Full specification for a connector to be scaffolded."""

    app_type: str = Field(description="Slug identifier, e.g. 'slack'")
    app_name: str = Field(description="Human-readable name, e.g. 'Slack Connector'")
    version: str = "v1"
    actions: list[ActionSpec] = Field(default_factory=list)
    triggers: list[TriggerSpec] = Field(default_factory=list)
    auth: AuthSpec = Field(default_factory=AuthSpec)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    ambiguities: list[AmbiguitySpec] = Field(default_factory=list)

    @property
    def needs_clarification(self) -> bool:
        return self.confidence < 0.85 and len(self.ambiguities) > 0

    @property
    def directory_name(self) -> str:
        return f"{self.app_type}-connector"
