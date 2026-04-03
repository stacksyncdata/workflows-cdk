"""
Capability registry -- loads all YAML manifests and provides lookup / search.

Usage::

    registry = CapabilityRegistry()        # auto-loads built-in manifests
    registry.load_directory(Path("./custom_capabilities"))  # extend with user-provided
    slack = registry.get("slack")          # by slug
    hits  = registry.search("send message slack")  # keyword search
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .manifest import AppManifest

logger = logging.getLogger(__name__)

_BUILTIN_DIR = Path(__file__).parent / "capabilities"


class CapabilityRegistry:
    """In-memory index of every known app manifest."""

    def __init__(self, *, load_builtins: bool = True) -> None:
        self._manifests: dict[str, AppManifest] = {}
        if load_builtins:
            self.load_directory(_BUILTIN_DIR)

    def load_directory(self, directory: Path) -> None:
        if not directory.is_dir():
            logger.warning("Capabilities directory not found: %s", directory)
            return
        for path in sorted(directory.glob("*.yaml")):
            try:
                manifest = AppManifest.from_yaml(path)
                self._manifests[manifest.app.slug] = manifest
            except Exception:
                logger.warning("Failed to load manifest %s", path, exc_info=True)

    def get(self, slug: str) -> Optional[AppManifest]:
        return self._manifests.get(slug)

    def all(self) -> list[AppManifest]:
        return list(self._manifests.values())

    def slugs(self) -> list[str]:
        return sorted(self._manifests.keys())

    def search(self, query: str) -> list[AppManifest]:
        """Rank manifests by simple keyword overlap with *query*."""
        tokens = set(query.lower().split())
        scored: list[tuple[int, AppManifest]] = []

        for manifest in self._manifests.values():
            corpus = " ".join([
                manifest.app.name.lower(),
                manifest.app.slug.lower(),
                manifest.app.description.lower(),
                " ".join(manifest.examples).lower(),
                " ".join(a.name.replace("_", " ") for a in manifest.actions),
                " ".join(a.description.lower() for a in manifest.actions),
                " ".join(t.name.replace("_", " ") for t in manifest.triggers),
            ])
            score = sum(1 for t in tokens if t in corpus)
            if score > 0:
                scored.append((score, manifest))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [m for _, m in scored]

    def summaries_for_llm(self) -> list[dict]:
        """All manifests in the compact dict format consumed by the planner prompt."""
        return [m.summary_for_llm() for m in self._manifests.values()]
