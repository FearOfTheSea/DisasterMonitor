import csv
import io
import json
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.evidence.provenance_graph import (
    ProvenanceGraphBuilder,
    ProvenanceNodeKind,
)
from disaster_monitor.application.evidence.why_evidence import ExplainEvidenceTrace
from disaster_monitor.application.incidents.country_association import (
    CountryAssociationBasis,
    IncidentCountryAssociation,
)
from disaster_monitor.application.incidents.models import (
    ActiveIncident,
    ActiveIncidentsSnapshot,
    DisasterIncidentCoverage,
    IncidentCoverageState,
)
from disaster_monitor.application.interoperability.exports import (
    HumanitarianContextRow,
    StacArtifactRecord,
    export_findings_csv,
    export_findings_geojson,
    export_hxl_csv,
    export_incidents_csv,
    export_incidents_geojson,
    export_stac_catalog,
)
from disaster_monitor.application.interoperability.feeds import export_watch_atom
from disaster_monitor.application.interoperability.incident_brief import (
    DeterministicIncidentBriefBuilder,
)
from disaster_monitor.application.interoperability.ogc_features import (
    OgcFeatureProjection,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
    IncidentActivityStatus,
    IncidentChangeKind,
    IncidentWatchChange,
    ProviderTier,
    SourceAuthority,
    SourceReference,
)

NOW = datetime(2026, 9, 15, 8, tzinfo=UTC)


def test_geojson_csv_and_ogc_exports_preserve_meaning_and_time_bounds() -> None:
    snapshot = _snapshot()

    geojson = export_incidents_geojson(snapshot)
    assert geojson["type"] == "FeatureCollection"
    assert geojson["features"][0]["geometry"]["type"] == "Point"
    assert geojson["features"][0]["properties"]["geometryMeaning"] == (
        "source_backed_event_point"
    )
    assert geojson["features"][0]["properties"]["sourceAuthority"] == (
        "scientific_authority"
    )

    rows = list(csv.DictReader(io.StringIO(export_incidents_csv(snapshot))))
    assert rows[0]["record_type"] == "incident"
    assert rows[0]["coverage_state"] == "events_found"
    assert rows[0]["event_time"] == "2026-09-15T07:00:00Z"

    collection = OgcFeatureProjection(snapshot).query(
        "incidents",
        bbox=(105, 20, 107, 22),
        occurrence_start=NOW - timedelta(hours=2),
        occurrence_end=NOW,
        limit=10,
    )
    assert collection["numberMatched"] == 1
    assert collection["timeStamp"] == "2026-09-15T08:00:00Z"
    assert collection["links"][0]["rel"] == "self"


def test_print_brief_is_deterministic_html_without_model_text() -> None:
    incident = _snapshot().incidents[0]
    result = DeterministicIncidentBriefBuilder().build(
        incident,
        coverage=_snapshot().coverage[0],
        retrieved_at=NOW,
        gaps=("No verified impact count was supplied.",),
    )

    assert result.title == "Earthquake — Test Region"
    assert "No verified impact count" in result.html
    assert "USGS" in result.html
    assert "print()" not in result.html
    assert result.generated_by == "deterministic-incident-brief:v1"


def test_stac_and_hxl_exports_are_standard_interchange_layers() -> None:
    stac = export_stac_catalog(
        (
            StacArtifactRecord(
                artifact_id="artifact:one",
                incident_id="event-1",
                datetime=NOW,
                geometry={
                    "type": "Polygon",
                    "coordinates": [
                        [[106, 21], [107, 21], [107, 22], [106, 22], [106, 21]]
                    ],
                },
                bbox=(106, 21, 107, 22),
                asset_href="/api/v1/ground-imagery/artifacts/artifact:one/download",
                media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                roles=("data", "analysis"),
                source_product_ids=("S1-before", "S1-after"),
                algorithm_version="sentinel-1-flood-change:1.0.0",
            ),
        )
    )
    assert stac["type"] == "Catalog"
    assert stac["links"][1]["rel"] == "item"
    item = stac["items"][0]
    assert item["stac_version"] == "1.0.0"
    assert item["assets"]["data"]["roles"] == ["data", "analysis"]

    hxl = export_hxl_csv(
        (
            HumanitarianContextRow(
                country_code="VNM",
                admin_name="Test Province",
                indicator="baseline population",
                value="125000",
                unit="people",
                source_url="https://data.example.test/population",
                as_of=NOW,
            ),
        )
    )
    lines = hxl.splitlines()
    assert lines[1].startswith("#country+code,#adm1+name,#indicator")
    assert "125000" in lines[2]


def test_atom_feed_and_provenance_trace_are_stable_and_inspectable() -> None:
    incident = _snapshot().incidents[0]
    change = IncidentWatchChange(
        change_id="change-1",
        watch_id="watch-1",
        kind=IncidentChangeKind.NEW_EVENT,
        summary="New earthquake",
        detail="A source-backed event entered the bounded result.",
        created_at=NOW,
        source_ids=("usgs-earthquakes",),
        observation_id="watch-observation-1",
        previous_observation_id=None,
        before_hash=None,
        after_hash="a" * 64,
        incident=incident,
    )
    atom = export_watch_atom("watch-1", (change,), base_url="http://localhost:8000")
    assert '<feed xmlns="http://www.w3.org/2005/Atom">' in atom
    assert "change-1" in atom
    assert "New earthquake" in atom

    finding_geojson = export_findings_geojson((change,))
    assert finding_geojson["features"][0]["id"] == "change-1"
    assert finding_geojson["features"][0]["geometry"]["type"] == "Point"
    finding_rows = list(csv.DictReader(io.StringIO(export_findings_csv((change,)))))
    assert finding_rows[0]["event_id"] == "event-1"
    assert finding_rows[0]["source_ids"] == "usgs-earthquakes"

    graph = ProvenanceGraphBuilder().for_incident(incident)
    assert {node.kind for node in graph.nodes} >= {
        ProvenanceNodeKind.PHYSICAL_EVENT,
        ProvenanceNodeKind.SOURCE_OBSERVATION,
        ProvenanceNodeKind.NORMALIZED_EVIDENCE,
    }
    trace = ExplainEvidenceTrace().for_event(incident.event_id, graph)
    assert trace.event_id == incident.event_id
    assert trace.source_ids == ("usgs-earthquakes",)
    assert "The trace is deterministic" in trace.limitation
    assert json.loads(trace.model_context)["event_id"] == "event-1"


def _source() -> SourceReference:
    return SourceReference(
        source_id="usgs-earthquakes",
        publisher="USGS",
        title="M 6.2 - Test Region",
        canonical_url="https://earthquake.usgs.gov/earthquakes/eventpage/test",
        published_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(minutes=30),
        retrieved_at=NOW,
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
        snapshot_id="snapshot:test",
    )


def _snapshot() -> ActiveIncidentsSnapshot:
    source = _source()
    incident = ActiveIncident(
        event_id="event-1",
        physical_event_id="physical-event:one",
        disaster=Disaster.EARTHQUAKE,
        country=IncidentCountryAssociation(
            "VNM", "Vietnam", CountryAssociationBasis.COORDINATE_POLYGON
        ),
        location="Test Region",
        event_time=NOW - timedelta(hours=1),
        geometry=EventGeometry(
            EventGeometryKind.POINT,
            source,
            (EventCoordinate(21, 106),),
        ),
        measurements=(),
        provider_ids=("usgs:event-1",),
        lineage_ids=("lineage:usgs:event-1",),
        provider_tier=ProviderTier.PRIMARY,
        source_authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
        source=source,
        evidence_sources=(source,),
        activity_status=IncidentActivityStatus.ENDED,
    )
    coverage = DisasterIncidentCoverage(
        Disaster.EARTHQUAKE,
        IncidentCoverageState.EVENTS_FOUND,
        1,
        ("USGS",),
        "One event found.",
        records_seen=1,
    )
    return ActiveIncidentsSnapshot(
        retrieved_at=NOW,
        incidents=(incident,),
        coverage=(coverage,),
        warnings=(),
        snapshot_version="incident-snapshot:test",
    )
