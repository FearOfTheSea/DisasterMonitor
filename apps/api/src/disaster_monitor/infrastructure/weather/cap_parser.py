"""Bounded parser for OASIS CAP 1.2 XML warning messages."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from disaster_monitor.application.ports.temporal_normalization import (
    normalize_timestamp,
)
from disaster_monitor.domain.imagery.regions import (
    Coordinate,
    MultiPolygon,
    polygon_from_geojson,
)
from disaster_monitor.domain.warnings import (
    CapAlert,
    CapArea,
    CapCircle,
    CapInfo,
    CapMessageReference,
    CapMessageType,
    CapScope,
    CapStatus,
    WarningCertainty,
    WarningSeverity,
    WarningUrgency,
)

_CAP_NAMESPACE = "urn:oasis:names:tc:emergency:cap:1.2"
_XML_SIGNATURE_NAMESPACE = "http://www.w3.org/2000/09/xmldsig#"
_MAX_INFOS = 32
_MAX_AREAS = 100
_MAX_POLYGONS = 100
_MAX_COORDINATES = 20_000


def parse_cap_alert(
    payload: bytes,
    *,
    source_id: str,
    publisher: str,
    canonical_url: str | None,
    retrieved_at: datetime,
    attribution: str,
    limitations: tuple[str, ...],
    profile: str | None = None,
) -> CapAlert:
    if len(payload) > 5_000_000:
        raise ValueError("CAP payload exceeds the parser limit.")
    root = ElementTree.fromstring(payload)
    if root.tag != _tag("alert"):
        raise ValueError("The document is not an OASIS CAP 1.2 alert.")
    info_nodes = root.findall(_tag("info"))
    if len(info_nodes) > _MAX_INFOS:
        raise ValueError("CAP info block count exceeds the parser limit.")
    return CapAlert(
        identifier=_required_text(root, "identifier"),
        sender=_required_text(root, "sender"),
        sent=_required_time(root, "sent"),
        status=_enum(CapStatus, _required_text(root, "status")),
        message_type=_enum(CapMessageType, _required_text(root, "msgType")),
        scope=_enum(CapScope, _required_text(root, "scope")),
        source_id=source_id,
        publisher=publisher,
        infos=tuple(_parse_info(node) for node in info_nodes),
        references=_references(_optional_text(root, "references")),
        incidents=_tokens(_optional_text(root, "incidents")),
        canonical_url=canonical_url,
        source=_optional_text(root, "source"),
        restriction=_optional_text(root, "restriction"),
        addresses=_tokens(_optional_text(root, "addresses")),
        codes=tuple(
            _node_text(item) for item in root.findall(_tag("code")) if _node_text(item)
        ),
        note=_optional_text(root, "note"),
        retrieved_at=retrieved_at,
        attribution=attribution,
        limitations=limitations,
        profile=profile,
        signature_present=(
            root.find(f"{{{_XML_SIGNATURE_NAMESPACE}}}Signature") is not None
        ),
        signature_verified=None,
    )


def _parse_info(node: Element) -> CapInfo:
    area_nodes = node.findall(_tag("area"))
    if len(area_nodes) > _MAX_AREAS:
        raise ValueError("CAP area count exceeds the parser limit.")
    return CapInfo(
        language=_optional_text(node, "language") or "en-US",
        categories=tuple(
            _node_text(item)
            for item in node.findall(_tag("category"))
            if _node_text(item)
        ),
        event=_required_text(node, "event"),
        event_codes=tuple(
            _name_value(item) for item in node.findall(_tag("eventCode"))
        ),
        urgency=_enum(WarningUrgency, _required_text(node, "urgency")),
        severity=_enum(WarningSeverity, _required_text(node, "severity")),
        certainty=_enum(WarningCertainty, _required_text(node, "certainty")),
        effective=_optional_time(node, "effective"),
        onset=_optional_time(node, "onset"),
        expires=_optional_time(node, "expires"),
        sender_name=_optional_text(node, "senderName"),
        headline=_optional_text(node, "headline"),
        description=_optional_text(node, "description"),
        instruction=_optional_text(node, "instruction"),
        areas=tuple(_parse_area(item) for item in area_nodes),
        parameters=tuple(_name_value(item) for item in node.findall(_tag("parameter"))),
    )


def _parse_area(node: Element) -> CapArea:
    polygon_nodes = node.findall(_tag("polygon"))
    if len(polygon_nodes) > _MAX_POLYGONS:
        raise ValueError("CAP polygon count exceeds the parser limit.")
    polygons = tuple(_parse_polygon(_node_text(item)) for item in polygon_nodes)
    if sum(item.positions for item in polygons) > _MAX_COORDINATES:
        raise ValueError("CAP coordinate count exceeds the parser limit.")
    return CapArea(
        description=_required_text(node, "areaDesc"),
        polygons=polygons,
        circles=tuple(
            _parse_circle(_node_text(item)) for item in node.findall(_tag("circle"))
        ),
        geocodes=tuple(_name_value(item) for item in node.findall(_tag("geocode"))),
        altitude_m=_optional_float(node, "altitude"),
        ceiling_m=_optional_float(node, "ceiling"),
    )


def _parse_polygon(value: str) -> MultiPolygon:
    pairs: list[list[float]] = []
    for token in value.split():
        latitude_text, separator, longitude_text = token.partition(",")
        if not separator:
            raise ValueError("A CAP polygon coordinate pair is malformed.")
        pairs.append([float(longitude_text), float(latitude_text)])
    return polygon_from_geojson({"type": "Polygon", "coordinates": [pairs]})


def _parse_circle(value: str) -> CapCircle:
    center, separator, radius = value.partition(" ")
    latitude, comma, longitude = center.partition(",")
    if not separator or not comma:
        raise ValueError("A CAP circle is malformed.")
    return CapCircle(Coordinate(float(latitude), float(longitude)), float(radius))


def _references(value: str | None) -> tuple[CapMessageReference, ...]:
    if value is None:
        return ()
    result: list[CapMessageReference] = []
    for token in value.split():
        sender, separator, remainder = token.partition(",")
        identifier, second_separator, sent_text = remainder.partition(",")
        sent = normalize_timestamp(sent_text)
        if not separator or not second_separator or sent is None:
            raise ValueError("A CAP message reference is malformed.")
        result.append(CapMessageReference(sender, identifier, sent))
    return tuple(result)


def _name_value(node: Element) -> tuple[str, str]:
    return _required_text(node, "valueName"), _required_text(node, "value")


def _tag(name: str) -> str:
    return f"{{{_CAP_NAMESPACE}}}{name}"


def _node_text(node: Element) -> str:
    return (node.text or "").strip()


def _optional_text(node: Element, name: str) -> str | None:
    child = node.find(_tag(name))
    value = _node_text(child) if child is not None else ""
    return value or None


def _required_text(node: Element, name: str) -> str:
    value = _optional_text(node, name)
    if value is None:
        raise ValueError(f"CAP field {name} is required.")
    return value


def _optional_time(node: Element, name: str) -> datetime | None:
    value = _optional_text(node, name)
    parsed = normalize_timestamp(value)
    if value is not None and parsed is None:
        raise ValueError(f"CAP field {name} is not a valid timestamp.")
    return parsed


def _required_time(node: Element, name: str) -> datetime:
    value = _optional_time(node, name)
    if value is None:
        raise ValueError(f"CAP field {name} is required.")
    return value


def _optional_float(node: Element, name: str) -> float | None:
    value = _optional_text(node, name)
    return None if value is None else float(value)


def _tokens(value: str | None) -> tuple[str, ...]:
    return tuple(value.split()) if value else ()


def _enum[EnumValue: StrEnum](enum_type: type[EnumValue], value: str) -> EnumValue:
    try:
        return enum_type(value.casefold())
    except ValueError as error:
        raise ValueError(f"Unsupported CAP value {value!r}.") from error
