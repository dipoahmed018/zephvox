"""Turn "these analyzers are enabled" into "compute these artifacts with these providers"."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .artifacts import ArtifactRegistry
from .errors import PlanError


@dataclass
class Plan:
    artifacts: list[str] = field(default_factory=list)  # dependency order
    provider_kinds: list[str] = field(default_factory=list)


def plan(
    requirements: Iterable[tuple[Iterable[str], Iterable[str]]],
    registry: ArtifactRegistry,
    provided: Iterable[str] = ("audio",),
) -> Plan:
    """`requirements` is one `(needs, uses)` pair per analyzer."""
    result = Plan()
    provided = set(provided)
    visiting: set[str] = set()

    def add_kind(kind: str) -> None:
        if kind not in result.provider_kinds:
            result.provider_kinds.append(kind)

    def visit(key: str, chain: tuple[str, ...]) -> None:
        if key in provided or key in result.artifacts:
            return
        if key in visiting:
            raise PlanError(f"Artifact dependency cycle: {' -> '.join((*chain, key))}")
        spec = registry.get(key)
        if spec is None:
            raise PlanError(f"No producer for artifact {key!r} (needed by {' -> '.join(chain) or 'analyzer'})")
        visiting.add(key)
        for need in spec.needs:
            visit(need, (*chain, key))
        visiting.discard(key)
        for kind in spec.uses:
            add_kind(kind)
        result.artifacts.append(key)

    for needs, uses in requirements:
        for key in needs:
            visit(key, ())
        for kind in uses:
            add_kind(kind)
    return result
