"""Deterministic evidence traces for 'why do you believe this?' requests."""

from __future__ import annotations

import json
from dataclasses import dataclass

from disaster_monitor.application.evidence.provenance_graph import (
    ProvenanceGraph,
    ProvenanceNodeKind,
)


@dataclass(frozen=True, slots=True)
class EvidenceTrace:
    event_id: str
    graph_id: str
    node_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    model_context: str
    limitation: str


class ExplainEvidenceTrace:
    """Select evidence deterministically before any optional model explanation."""

    def for_event(self, event_id: str, graph: ProvenanceGraph) -> EvidenceTrace:
        target = f"event:{event_id}"
        if not any(node.node_id == target for node in graph.nodes):
            raise ValueError(
                "The requested event is not present in the provenance graph."
            )
        included = {target}
        changed = True
        while changed:
            changed = False
            for edge in graph.edges:
                if edge.to_node_id in included and edge.from_node_id not in included:
                    included.add(edge.from_node_id)
                    changed = True
                if edge.from_node_id in included and edge.to_node_id not in included:
                    included.add(edge.to_node_id)
                    changed = True
        nodes = tuple(node for node in graph.nodes if node.node_id in included)
        source_ids = tuple(
            sorted(
                {
                    node.source_id
                    for node in nodes
                    if node.kind is ProvenanceNodeKind.SOURCE_OBSERVATION
                    and node.source_id is not None
                }
            )
        )
        context = json.dumps(
            {
                "event_id": event_id,
                "graph_id": graph.graph_id,
                "nodes": [
                    {
                        "id": node.node_id,
                        "kind": node.kind.value,
                        "label": node.label,
                        "source_id": node.source_id,
                        "reference": node.reference,
                    }
                    for node in nodes
                ],
                "edges": [
                    {
                        "kind": edge.kind.value,
                        "from": edge.from_node_id,
                        "to": edge.to_node_id,
                    }
                    for edge in graph.edges
                    if edge.from_node_id in included and edge.to_node_id in included
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return EvidenceTrace(
            event_id=event_id,
            graph_id=graph.graph_id,
            node_ids=tuple(node.node_id for node in nodes),
            source_ids=source_ids,
            model_context=context,
            limitation=(
                "The trace is deterministic and includes only already-admitted "
                "provenance; an optional model may explain but not extend it."
            ),
        )


__all__ = ["EvidenceTrace", "ExplainEvidenceTrace"]
