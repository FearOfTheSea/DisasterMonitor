"""Stable typed provenance graph for incident evidence inspection."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from disaster_monitor.domain.disaster import Disaster, SourceReference


class IncidentProvenanceInput(Protocol):
    """Narrow evidence input independent of the incident-view capability."""

    @property
    def event_id(self) -> str: ...

    @property
    def location(self) -> str: ...

    @property
    def disaster(self) -> Disaster: ...

    @property
    def source(self) -> SourceReference: ...

    @property
    def evidence_sources(self) -> tuple[SourceReference, ...]: ...


class ProvenanceNodeKind(StrEnum):
    PHYSICAL_EVENT = "physical_event"
    SOURCE_OBSERVATION = "source_observation"
    NORMALIZED_EVIDENCE = "normalized_evidence"
    ANALYTICAL_ARTIFACT = "analytical_artifact"
    FINDING = "finding"
    REPORT_CLAIM = "report_claim"


class ProvenanceEdgeKind(StrEnum):
    WAS_DERIVED_FROM = "was_derived_from"
    WAS_GENERATED_BY = "was_generated_by"
    SUPPORTS = "supports"


@dataclass(frozen=True, slots=True)
class ProvenanceNode:
    node_id: str
    kind: ProvenanceNodeKind
    label: str
    source_id: str | None = None
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class ProvenanceEdge:
    edge_id: str
    kind: ProvenanceEdgeKind
    from_node_id: str
    to_node_id: str


@dataclass(frozen=True, slots=True)
class ProvenanceGraph:
    graph_id: str
    nodes: tuple[ProvenanceNode, ...]
    edges: tuple[ProvenanceEdge, ...]


class ProvenanceGraphBuilder:
    def for_incident(self, incident: IncidentProvenanceInput) -> ProvenanceGraph:
        event_node = ProvenanceNode(
            f"event:{incident.event_id}",
            ProvenanceNodeKind.PHYSICAL_EVENT,
            incident.location,
        )
        normalized_node = ProvenanceNode(
            f"evidence:{incident.event_id}",
            ProvenanceNodeKind.NORMALIZED_EVIDENCE,
            f"Normalized {incident.disaster.value.replace('_', ' ')} evidence",
        )
        sources = incident.evidence_sources or (incident.source,)
        source_nodes = tuple(
            ProvenanceNode(
                f"source-observation:{source.source_id}:{incident.event_id}",
                ProvenanceNodeKind.SOURCE_OBSERVATION,
                source.title,
                source_id=source.source_id,
                reference=source.canonical_url,
            )
            for source in sorted(sources, key=lambda value: value.source_id)
        )
        edges = [
            _edge(
                ProvenanceEdgeKind.WAS_DERIVED_FROM,
                normalized_node.node_id,
                source_node.node_id,
            )
            for source_node in source_nodes
        ]
        edges.append(
            _edge(
                ProvenanceEdgeKind.SUPPORTS,
                normalized_node.node_id,
                event_node.node_id,
            )
        )
        nodes = (event_node, *source_nodes, normalized_node)
        material = "|".join(node.node_id for node in nodes)
        return ProvenanceGraph(
            "provenance-graph:" + hashlib.sha256(material.encode()).hexdigest()[:24],
            nodes,
            tuple(edges),
        )


def _edge(kind: ProvenanceEdgeKind, source: str, target: str) -> ProvenanceEdge:
    material = f"{kind.value}|{source}|{target}"
    return ProvenanceEdge(
        "provenance-edge:" + hashlib.sha256(material.encode()).hexdigest()[:24],
        kind,
        source,
        target,
    )


__all__ = [
    "ProvenanceEdge",
    "ProvenanceEdgeKind",
    "ProvenanceGraph",
    "ProvenanceGraphBuilder",
    "ProvenanceNode",
    "ProvenanceNodeKind",
]
