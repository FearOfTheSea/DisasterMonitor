from dataclasses import replace
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.warnings.association import (
    WarningAssociationBasis,
    associate_earthquake_tsunami_warning,
    associate_warning,
)
from disaster_monitor.application.warnings.lifecycle import reconcile_cap_messages
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.imagery.regions import polygon_from_geojson
from disaster_monitor.domain.warnings import (
    CapAlert,
    CapArea,
    CapInfo,
    CapMessageReference,
    CapMessageType,
    CapScope,
    CapStatus,
    WarningCertainty,
    WarningLifecycleState,
    WarningSeverity,
    WarningUrgency,
)

NOW = datetime(2026, 9, 14, 4, tzinfo=UTC)


def _alert(
    identifier: str,
    message_type: CapMessageType,
    *,
    sent: datetime,
    references: tuple[CapMessageReference, ...] = (),
    expires: datetime | None = None,
    language: str = "en-US",
    event: str = "Flood Warning",
) -> CapAlert:
    geometry = polygon_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [
                [[106.0, 10.0], [107.0, 10.0], [107.0, 11.0], [106.0, 10.0]]
            ],
        }
    )
    return CapAlert(
        identifier=identifier,
        sender="warnings.example",
        sent=sent,
        status=CapStatus.ACTUAL,
        message_type=message_type,
        scope=CapScope.PUBLIC,
        source_id="fixture-cap",
        publisher="Fixture Warning Authority",
        infos=(
            CapInfo(
                language=language,
                categories=("Met",),
                event=event,
                event_codes=(("profile:event", "FL"),),
                urgency=WarningUrgency.EXPECTED,
                severity=WarningSeverity.SEVERE,
                certainty=WarningCertainty.LIKELY,
                effective=sent,
                onset=sent + timedelta(minutes=10),
                expires=expires or sent + timedelta(hours=4),
                sender_name="Fixture Warning Authority",
                headline=f"{event} ({language})",
                description="Source description",
                instruction="Follow the issuing authority.",
                areas=(CapArea("River basin", polygons=(geometry,)),),
            ),
        ),
        references=references,
        incidents=("incident-42",),
        canonical_url=f"https://warnings.example/{identifier}",
        retrieved_at=NOW,
        attribution="Fixture attribution",
        limitations=("Warning evidence is not physical-event confirmation.",),
        profile="CAP-1.2",
        signature_present=True,
        signature_verified=None,
    )


def test_cap_model_retains_multilingual_blocks_and_profile_metadata() -> None:
    alert = _alert("initial", CapMessageType.ALERT, sent=NOW - timedelta(hours=1))
    translated = _alert(
        "translated",
        CapMessageType.ALERT,
        sent=NOW - timedelta(minutes=50),
        language="vi",
    )

    assert alert.infos[0].areas[0].polygons[0].positions == 4
    assert alert.signature_present is True
    assert translated.infos[0].language == "vi"
    assert alert.hazard_candidates == (Disaster.FLOOD,)


def test_lifecycle_update_cancel_duplicate_and_expiry_are_reconciled() -> None:
    initial = _alert("initial", CapMessageType.ALERT, sent=NOW - timedelta(hours=2))
    reference = CapMessageReference(initial.sender, initial.identifier, initial.sent)
    update = _alert(
        "update",
        CapMessageType.UPDATE,
        sent=NOW - timedelta(hours=1),
        references=(reference,),
    )
    duplicate = _alert(
        "update",
        CapMessageType.UPDATE,
        sent=NOW - timedelta(hours=1),
        references=(reference,),
    )
    cancel_reference = CapMessageReference(
        update.sender, update.identifier, update.sent
    )
    cancel = _alert(
        "cancel",
        CapMessageType.CANCEL,
        sent=NOW - timedelta(minutes=5),
        references=(cancel_reference,),
    )
    expired = _alert(
        "expired",
        CapMessageType.ALERT,
        sent=NOW - timedelta(days=1),
        expires=NOW - timedelta(minutes=1),
    )

    reconciled = reconcile_cap_messages(
        (initial, update, duplicate, cancel, expired), now=NOW
    )

    assert [(item.alert.identifier, item.state) for item in reconciled] == [
        ("cancel", WarningLifecycleState.CANCELLED),
        ("expired", WarningLifecycleState.EXPIRED),
    ]
    assert reconciled[0].superseded_identifiers == ("initial", "update")


def test_warning_association_prefers_explicit_ids_and_labels_geometry_gate() -> None:
    alert = _alert("initial", CapMessageType.ALERT, sent=NOW - timedelta(minutes=20))
    explicit = associate_warning(
        alert,
        disaster=Disaster.FLOOD,
        event_id="incident-42",
        event_time=NOW - timedelta(minutes=30),
        event_geometry=alert.infos[0].areas[0].polygons[0],
    )
    gated = associate_warning(
        alert,
        disaster=Disaster.FLOOD,
        event_id="different",
        event_time=NOW - timedelta(minutes=30),
        event_geometry=alert.infos[0].areas[0].polygons[0],
    )
    incompatible = associate_warning(
        alert,
        disaster=Disaster.EARTHQUAKE,
        event_id="different",
        event_time=NOW - timedelta(minutes=30),
        event_geometry=alert.infos[0].areas[0].polygons[0],
    )

    assert explicit.basis is WarningAssociationBasis.EXPLICIT_INCIDENT_ID
    assert gated.basis is WarningAssociationBasis.TIME_AND_GEOMETRY
    assert gated.confirmed is False
    assert incompatible is None


def test_tsunami_warning_association_requires_authority_and_hazard_identity() -> None:
    explicit_alert = replace(
        _alert(
            "tsunami-explicit",
            CapMessageType.ALERT,
            sent=NOW,
            event="Tsunami Warning",
        ),
        incidents=("usgs:quake-1",),
    )
    explicit = associate_earthquake_tsunami_warning(
        explicit_alert,
        earthquake_event_id="usgs:quake-1",
        earthquake_time=NOW,
        earthquake_latitude=35.0,
        earthquake_longitude=140.0,
        authoritative_source_ids=("fixture-cap",),
    )
    unrelated = associate_earthquake_tsunami_warning(
        _alert(
            "flood-alert",
            CapMessageType.ALERT,
            sent=NOW,
            event="Flood Warning",
        ),
        earthquake_event_id="usgs:quake-1",
        earthquake_time=NOW,
        earthquake_latitude=35.0,
        earthquake_longitude=140.0,
        authoritative_source_ids=("fixture-cap",),
    )

    assert explicit is not None
    assert explicit.confirmed is True
    assert explicit.basis is WarningAssociationBasis.EXPLICIT_INCIDENT_ID
    assert unrelated is None
