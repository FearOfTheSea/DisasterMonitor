"""Versioned serialization for application-owned assistant response state."""

from __future__ import annotations

import base64
import types
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum, StrEnum
from typing import Any, Union, cast, get_args, get_origin, get_type_hints

from disaster_monitor.application.dto import AssistantAnswer
from disaster_monitor.domain.conversation import AssistantMessagePayload, JsonValue
from disaster_monitor.domain.disaster import Disaster

ASSISTANT_ANSWER_SCHEMA_VERSION = "assistant-answer.v1"


def assistant_message_payload(answer: AssistantAnswer) -> AssistantMessagePayload:
    """Encode one bounded application answer without persisting browser state."""
    encoded = _encode(answer)
    if not isinstance(encoded, dict):
        raise TypeError("An assistant answer must serialize to an object.")
    return AssistantMessagePayload(ASSISTANT_ANSWER_SCHEMA_VERSION, encoded)


def assistant_answer_from_payload(
    payload: AssistantMessagePayload | None,
) -> AssistantAnswer | None:
    """Decode a recognized payload; unknown or invalid versions remain text-only."""
    if payload is None or payload.schema_version != ASSISTANT_ANSWER_SCHEMA_VERSION:
        return None
    try:
        decoded = _decode(AssistantAnswer, payload.data)
    except (KeyError, TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, AssistantAnswer) else None


def _encode(value: object) -> JsonValue:
    if isinstance(value, Enum):
        return _encode(value.value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _encode(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Assistant payload object keys must be strings.")
        return {str(key): _encode(item) for key, item in value.items()}
    raise TypeError(f"Unsupported assistant payload value: {type(value).__name__}")


def _decode(annotation: object, value: JsonValue) -> object:
    origin = get_origin(annotation)
    if origin in {types.UnionType, Union}:
        if value is None and type(None) in get_args(annotation):
            return None
        for option in get_args(annotation):
            if option is type(None):
                continue
            try:
                return _decode(option, value)
            except (KeyError, TypeError, ValueError):
                continue
        raise TypeError("Assistant payload did not match its union type.")
    if origin is tuple:
        if not isinstance(value, list):
            raise TypeError("Assistant payload tuple must be an array.")
        arguments = get_args(annotation)
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return tuple(_decode(arguments[0], item) for item in value)
        if len(arguments) != len(value):
            raise ValueError("Assistant payload tuple length changed.")
        return tuple(
            _decode(item_type, item)
            for item_type, item in zip(arguments, value, strict=True)
        )
    if origin is list:
        if not isinstance(value, list):
            raise TypeError("Assistant payload list must be an array.")
        item_type = get_args(annotation)[0]
        return [_decode(item_type, item) for item in value]
    if origin is dict:
        if not isinstance(value, dict):
            raise TypeError("Assistant payload mapping must be an object.")
        key_type, item_type = get_args(annotation)
        if key_type is not str:
            raise TypeError("Assistant payload mappings require string keys.")
        return {key: _decode(item_type, item) for key, item in value.items()}
    if annotation in {Any, object}:
        return value
    if annotation is datetime:
        if not isinstance(value, str):
            raise TypeError("Assistant payload datetime must be a string.")
        return datetime.fromisoformat(value)
    if annotation is bytes:
        if not isinstance(value, dict) or set(value) != {"$bytes"}:
            raise TypeError("Assistant payload bytes are malformed.")
        encoded = value["$bytes"]
        if not isinstance(encoded, str):
            raise TypeError("Assistant payload bytes must be base64 text.")
        return base64.b64decode(encoded, validate=True)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        if not isinstance(value, str):
            raise TypeError("Assistant payload enum must be text.")
        enum_type = Disaster if annotation is StrEnum else annotation
        return enum_type(value)
    if isinstance(annotation, type) and is_dataclass(annotation):
        if not isinstance(value, dict):
            raise TypeError("Assistant payload dataclass must be an object.")
        annotations = get_type_hints(annotation)
        decoded_fields = {
            item.name: _decode(annotations[item.name], value[item.name])
            for item in fields(annotation)
        }
        constructor = cast(Any, annotation)
        return constructor(**decoded_fields)
    if annotation is str and isinstance(value, str):
        return value
    if annotation is bool and isinstance(value, bool):
        return value
    if annotation is int and isinstance(value, int) and not isinstance(value, bool):
        return value
    if annotation is float and isinstance(value, (int, float)):
        return float(value)
    raise TypeError("Assistant payload primitive type changed.")
