"""Deterministic rendering for an already-grounded investigation case."""

from collections.abc import Iterable

from disaster_monitor.application.agent.investigation_cases import (
    InvestigationCaseArtifact,
    InvestigationCaseReport,
)
from disaster_monitor.application.disaster import ReportSection
from disaster_monitor.domain.disaster import SourceReference


class InvestigationReportRenderer:
    """Merge branch reports without creating new factual claims."""

    def render(self, case: InvestigationCaseArtifact) -> InvestigationCaseReport:
        sections: list[ReportSection] = [
            ReportSection(
                "Investigation scope",
                "Current two-hazard investigation for "
                f"{case.country.country_name}: "
                + " and ".join(
                    item.target.disaster.value.replace("_", " ")
                    for item in case.targets
                )
                + ".",
            )
        ]
        for branch in case.targets:
            label = branch.target.disaster.value.replace("_", " ").title()
            branch_content = [
                f"Status: {branch.status.replace('_', ' ')}.",
                *(f"{item.title}: {item.content}" for item in branch.sections),
            ]
            if not branch.sections:
                branch_content.append(
                    "No grounded branch report was available for this requested hazard."
                )
            if branch.warnings:
                branch_content.append("Warnings: " + " ".join(branch.warnings))
            if branch.capability_gaps:
                branch_content.append(
                    "Coverage and capability gaps: " + " ".join(branch.capability_gaps)
                )
            sections.append(
                ReportSection(f"{label} investigation", "\n\n".join(branch_content))
            )
        assessment = case.cross_hazard_assessment
        correlation_text = "\n".join(
            f"- {item.summary} Distance: {item.distance_km:g} km; "
            f"time difference: {item.time_delta_seconds} seconds. {item.limitation}"
            for item in case.correlations
        )
        sections.append(
            ReportSection(
                "Cross-hazard assessment",
                "\n\n".join(
                    item
                    for item in (
                        assessment.summary,
                        correlation_text,
                        assessment.limitation,
                    )
                    if item
                ),
            )
        )
        sources = tuple(
            _deduplicated_sources(branch.sources for branch in case.targets)
        )
        if sources:
            sections.append(
                ReportSection(
                    "Sources",
                    "\n".join(
                        f"- {source.publisher} — {source.title} "
                        f"({source.canonical_url})"
                        for source in sources
                    ),
                )
            )
        warnings = tuple(
            dict.fromkeys(
                warning for branch in case.targets for warning in branch.warnings
            )
        )
        return InvestigationCaseReport(
            message="\n\n".join(
                f"## {section.title}\n{section.content}" for section in sections
            ),
            sources=sources,
            warnings=warnings,
            sections=tuple(sections),
            partial=case.partial,
        )


def _deduplicated_sources(
    source_groups: Iterable[tuple[SourceReference, ...]],
) -> Iterable[SourceReference]:
    seen: set[str] = set()
    for source in (source for group in source_groups for source in group):
        if source.source_id not in seen:
            seen.add(source.source_id)
            yield source
