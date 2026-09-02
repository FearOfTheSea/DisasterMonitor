"""FastAPI routes for the MVP."""

import base64
import binascii
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from disaster_monitor.application.assistant_message_payload import (
    assistant_answer_from_payload,
)
from disaster_monitor.application.multimodal import AssetAdmissionInput
from disaster_monitor.application.ports.conversation_store import ConversationStore
from disaster_monitor.application.use_cases.delete_conversation import (
    DeleteConversation,
)
from disaster_monitor.application.use_cases.run_conversation_turn import (
    RunConversationTurn,
)
from disaster_monitor.domain.models import MapView
from disaster_monitor.presentation.http.multimodal_schemas import (
    MultimodalAssetRequest,
)
from disaster_monitor.presentation.http.response_serialization import (
    _assistant_response,
)
from disaster_monitor.presentation.http.schemas import (
    AssistantRequest,
    AssistantResponse,
    ConversationMessageResponse,
    ConversationResponse,
    ConversationSummaryResponse,
)

router = APIRouter()


def get_conversation_store(request: Request) -> ConversationStore:
    """Retrieve the conversation repository built by the composition root."""
    return cast(ConversationStore, request.app.state.dependencies.conversation_store)


def get_conversation_turn(request: Request) -> RunConversationTurn:
    """Retrieve the transcript-aware assistant use case."""
    return cast(
        RunConversationTurn, request.app.state.dependencies.run_conversation_turn
    )


def get_delete_conversation(request: Request) -> DeleteConversation:
    """Retrieve the atomic conversation-deletion use case."""
    return cast(DeleteConversation, request.app.state.dependencies.delete_conversation)


@router.post(
    "/assistant",
    response_model=AssistantResponse,
    response_model_exclude_unset=True,
    status_code=status.HTTP_200_OK,
    tags=["assistant"],
)
async def assistant(
    body: AssistantRequest,
    http_request: Request,
    use_case: Annotated[RunConversationTurn, Depends(get_conversation_turn)],
) -> AssistantResponse:
    """Answer a map-related question through the application use case."""
    result = await use_case.execute(
        question=body.question,
        conversation_id=body.conversation_id,
        map_view=(
            None
            if body.map_view is None
            else MapView(
                center_latitude=body.map_view.center_latitude,
                center_longitude=body.map_view.center_longitude,
                zoom=body.map_view.zoom,
            )
        ),
        multimodal_inputs=tuple(_asset_input(item) for item in body.multimodal_assets),
    )
    return _assistant_response(result, http_request)


@router.get(
    "/conversations",
    response_model=list[ConversationSummaryResponse],
    tags=["assistant"],
)
async def list_conversations(
    repository: Annotated[ConversationStore, Depends(get_conversation_store)],
) -> list[ConversationSummaryResponse]:
    """List durable conversations from newest update to oldest."""
    return [
        ConversationSummaryResponse(
            conversation_id=item.conversation_id,
            created_at=item.created_at,
            updated_at=item.updated_at,
            preview=item.preview,
        )
        for item in await repository.list()
    ]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    tags=["assistant"],
)
async def get_conversation(
    conversation_id: str,
    http_request: Request,
    repository: Annotated[ConversationStore, Depends(get_conversation_store)],
) -> ConversationResponse:
    """Return one stored transcript in chronological order."""
    conversation = await repository.get(conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested conversation does not exist.",
        )
    return ConversationResponse(
        conversation_id=conversation.conversation_id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            ConversationMessageResponse(
                id=message.message_id,
                role=message.role.value,
                content=message.content,
                created_at=message.created_at,
                assistant_response=(
                    _assistant_response(answer, http_request)
                    if (
                        answer := assistant_answer_from_payload(
                            message.assistant_payload
                        )
                    )
                    is not None
                    else None
                ),
            )
            for message in conversation.messages
        ],
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["assistant"],
)
async def delete_conversation(
    conversation_id: str,
    use_case: Annotated[DeleteConversation, Depends(get_delete_conversation)],
) -> Response:
    """Permanently remove a conversation and all lifecycle-owned state."""
    await use_case.execute(conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _asset_input(item: MultimodalAssetRequest) -> AssetAdmissionInput:
    try:
        content = base64.b64decode(item.content_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(
            status_code=422,
            detail="Multimodal asset content must be valid base64.",
        ) from error
    footprint = item.footprint
    return AssetAdmissionInput(
        content=content,
        attribution=item.attribution,
        captured_at=item.captured_at,
        footprint_coordinates=(
            None
            if footprint is None
            else tuple(
                tuple((longitude, latitude) for longitude, latitude in ring)
                for ring in footprint.coordinates
            )
        ),
        footprint_crs=footprint.crs if footprint else "EPSG:4326",
        declared_disaster=item.declared_disaster,
        declared_country_code=item.declared_country_code,
        capture_role=item.capture_role,
        canonical_url=item.canonical_url,
        dataset_id=item.dataset_id,
        license_name=item.license_name,
        processing_level=item.processing_level,
        parent_asset_ids=tuple(item.parent_asset_ids),
        event_id_hint=item.event_id_hint,
    )
