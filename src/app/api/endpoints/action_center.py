from fastapi import APIRouter, Depends

from app import depends
from models.dto.ActionCenterRequestDTO import ActionCenterExtractRequestDTO, ActionCenterStatusRequestDTO
from services.ActionIntelligenceService import ActionIntelligenceService

router = APIRouter()


@router.get("/items")
async def list_action_center_items(
    item_type: str = "",
    owner: str = "",
    topic: str = "",
    recording_name: str = "",
    date_filter: str = "",
    include_dismissed: bool = False,
    action_intelligence_service: ActionIntelligenceService = Depends(depends.get_action_intelligence_service),
):
    return action_intelligence_service.list_items(
        item_type=item_type,
        owner=owner,
        topic=topic,
        recording_name=recording_name,
        date_filter=date_filter,
        include_dismissed=include_dismissed,
    )


@router.post("/extract/selected")
async def extract_selected_recordings(
    body: ActionCenterExtractRequestDTO,
    action_intelligence_service: ActionIntelligenceService = Depends(depends.get_action_intelligence_service),
):
    return action_intelligence_service.extract_selected(body.names, force=body.force)


@router.post("/extract/summarized")
async def extract_all_summarized(
    body: ActionCenterExtractRequestDTO,
    action_intelligence_service: ActionIntelligenceService = Depends(depends.get_action_intelligence_service),
):
    return action_intelligence_service.extract_all_summarized(force=body.force)


@router.post("/extract/transcribed")
async def extract_all_transcribed(
    body: ActionCenterExtractRequestDTO,
    action_intelligence_service: ActionIntelligenceService = Depends(depends.get_action_intelligence_service),
):
    return action_intelligence_service.extract_all_transcribed(force=body.force)


@router.post("/extract/collection")
async def extract_collection(
    body: ActionCenterExtractRequestDTO,
    action_intelligence_service: ActionIntelligenceService = Depends(depends.get_action_intelligence_service),
):
    if body.collection_id is None:
        return {"ok": False, "error": "collection_id is required"}
    return action_intelligence_service.extract_collection(body.collection_id, force=body.force)


@router.post("/extract/recording/{name}")
async def regenerate_recording_extraction(
    name: str,
    body: ActionCenterExtractRequestDTO = ActionCenterExtractRequestDTO(),
    action_intelligence_service: ActionIntelligenceService = Depends(depends.get_action_intelligence_service),
):
    return action_intelligence_service.regenerate_recording(name)


@router.patch("/items/{item_id}/status")
async def update_action_center_item_status(
    item_id: int,
    body: ActionCenterStatusRequestDTO,
    action_intelligence_service: ActionIntelligenceService = Depends(depends.get_action_intelligence_service),
):
    return action_intelligence_service.update_item_status(item_id, body.status)


@router.post("/items/{item_id}/dismiss")
async def dismiss_action_center_item(
    item_id: int,
    action_intelligence_service: ActionIntelligenceService = Depends(depends.get_action_intelligence_service),
):
    return action_intelligence_service.dismiss_item(item_id)
