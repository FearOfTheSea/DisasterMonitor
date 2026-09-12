"""Strict primitive coercion helpers for the ground-imagery repository codec."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from disaster_monitor.application.ground_imagery.temporal_policy import AgeClass


def age_class(value: str) -> AgeClass:
    return AgeClass(value)


def mapping(document: Mapping[str, Any], name: str) -> dict[str, Any]:
    return mapping_value(document.get(name))


def mapping_value(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("A durable imagery document contains a non-object value.")
    return dict(value)


def list_value(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name)
    if not isinstance(value, list):
        raise ValueError(f"A durable imagery document field {name} is not a list.")
    return value


def string(document: Mapping[str, Any], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"A durable imagery document field {name} is not a string.")
    return value


def string_value(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"A durable imagery document item in {name} is not a string.")
    return value


def optional_string(document: Mapping[str, Any], name: str) -> str | None:
    value = document.get(name)
    return None if value is None else string(document, name)


def integer(document: Mapping[str, Any], name: str) -> int:
    value = document.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"A durable imagery document field {name} is not an integer.")
    return value


def number(document: Mapping[str, Any], name: str) -> float:
    value = document.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"A durable imagery document field {name} is not numeric.")
    return float(value)


def number_item(value: object) -> float:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("A component coverage entry must contain two values.")
    item = value[1]
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise ValueError("A component coverage value is not numeric.")
    return float(item)


def string_first(value: object, name: str) -> str:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"A durable imagery pair in {name} must contain two values.")
    return string_value(value[0], name)


def string_pair(value: object, name: str) -> tuple[str, str]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"A durable imagery pair in {name} must contain two values.")
    return string_value(value[0], name), string_value(value[1], name)


def datetime_value(document: Mapping[str, Any], name: str) -> datetime:
    value = string(document, name)
    return parse_datetime(value)


def optional_datetime(document: Mapping[str, Any], name: str) -> datetime | None:
    return None if document.get(name) is None else datetime_value(document, name)


def parse_datetime(value: object) -> datetime:
    return datetime.fromisoformat(string_value(value, "timestamp"))
