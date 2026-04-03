"""
Pydantic models that mirror the capability.yaml manifest format.

Each YAML file in ``registry/capabilities/`` is loaded into an
``AppManifest`` instance so both the LLM planner and the deterministic
validator work against a single, typed source of truth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field


class ManifestField(BaseModel):
    name: str
    type: Literal["string", "number", "boolean", "object", "array"] = "string"
    description: str = ""


class ManifestAuth(BaseModel):
    type: Literal["oauth2", "api_key", "basic", "none"] = "oauth2"
    scopes: list[str] = Field(default_factory=list)
    fields: list[ManifestField] = Field(default_factory=list)


class ManifestAction(BaseModel):
    name: str
    category: Literal["action", "trigger", "search", "transform"] = "action"
    description: str = ""
    required_fields: list[ManifestField] = Field(default_factory=list)
    optional_fields: list[ManifestField] = Field(default_factory=list)


class ManifestTrigger(BaseModel):
    name: str
    event: str = ""
    description: str = ""
    payload_fields: list[ManifestField] = Field(default_factory=list)


class ManifestApp(BaseModel):
    name: str
    slug: str
    description: str = ""
    auth: ManifestAuth = Field(default_factory=ManifestAuth)


class AppManifest(BaseModel):
    """Top-level model for a single ``capability.yaml`` file."""

    app: ManifestApp
    actions: list[ManifestAction] = Field(default_factory=list)
    triggers: list[ManifestTrigger] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> "AppManifest":
        with open(path, "r") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls.model_validate(raw)

    def action_names(self) -> list[str]:
        return [a.name for a in self.actions]

    def trigger_names(self) -> list[str]:
        return [t.name for t in self.triggers]

    def summary_for_llm(self) -> dict:
        """Compact JSON-serialisable summary injected into the LLM prompt."""
        return {
            "app": self.app.slug,
            "name": self.app.name,
            "description": self.app.description,
            "auth_type": self.app.auth.type,
            "actions": [
                {"name": a.name, "category": a.category, "description": a.description}
                for a in self.actions
            ],
            "triggers": [
                {"name": t.name, "event": t.event, "description": t.description}
                for t in self.triggers
            ],
        }
