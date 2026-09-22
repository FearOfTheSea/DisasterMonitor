"""Transport schemas for non-evidence workspace and bounded exports."""

from typing import Any

from pydantic import BaseModel, Field


class AnalystNoteRequest(BaseModel):
    incident_id: str | None = Field(default=None, max_length=500)
    text: str = Field(min_length=1, max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=50)


class BookmarkRequest(BaseModel):
    incident_id: str | None = Field(default=None, max_length=500)
    target_type: str = Field(min_length=1, max_length=100)
    target_id: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=500)


class RunbookTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    steps: list[str] = Field(min_length=1, max_length=100)


class CaseNotebookRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    created_by: str = Field(min_length=1, max_length=200)
    incident_ids: list[str] = Field(default_factory=list, max_length=100)


class NotebookEntryRequest(BaseModel):
    kind: str = Field(pattern="^(source_snapshot|question|analytical_run|conclusion)$")
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=20_000)
    reference_id: str | None = Field(default=None, max_length=500)
    created_by: str = Field(min_length=1, max_length=200)


class MappingWorkflowRequest(BaseModel):
    incident_id: str = Field(min_length=1, max_length=500)
    aoi: dict[str, Any]


class EvidencePackageCreateRequest(BaseModel):
    incident_id: str = Field(min_length=1, max_length=500)
    incident_snapshot: dict[str, Any]
    source_links: list[str] = Field(default_factory=list, max_length=1_000)
    normalized_data: dict[str, Any]
    findings: list[dict[str, Any]] = Field(default_factory=list, max_length=10_000)
    imagery_manifests: list[dict[str, Any]] = Field(
        default_factory=list, max_length=1_000
    )
    software_version: str = Field(min_length=1, max_length=100)
    policy_versions: list[str] = Field(default_factory=list, max_length=1_000)


class EvidencePackageVerifyRequest(BaseModel):
    content_base64: str = Field(min_length=1, max_length=70_000_000)
