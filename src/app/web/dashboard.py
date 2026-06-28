from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app import depends
from controllers.ActionCenterController import ActionCenterController
from controllers.CalendarController import CalendarController
from controllers.DashboardController import DashboardController
from controllers.ProcessingQueueController import ProcessingQueueController
from controllers.ProactorController import ProactorController

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, dashboard_controller: DashboardController = Depends(depends.get_dashboard_controller)):
    return dashboard_controller.home(request)


@router.get("/calendar", response_class=HTMLResponse)
def calendar_home(
    request: Request, calendar_controller: CalendarController = Depends(depends.get_calendar_controller)
):
    return calendar_controller.calendar_home(request)


@router.get("/proactor", response_class=HTMLResponse)
def proactor_home(
    request: Request, proactor_controller: ProactorController = Depends(depends.get_proactor_controller)
):
    return proactor_controller.proactor_home(request)


@router.get("/action-center", response_class=HTMLResponse)
def action_center_home(
    request: Request,
    action_center_controller: ActionCenterController = Depends(depends.get_action_center_controller),
):
    return action_center_controller.action_center_home(request)


@router.get("/processing-queue", response_class=HTMLResponse)
def processing_queue_home(
    request: Request,
    processing_queue_controller: ProcessingQueueController = Depends(depends.get_processing_queue_controller),
):
    return processing_queue_controller.processing_queue_home(request)


@router.get("/summary-pipeline", response_class=HTMLResponse)
def summary_pipeline_home(
    request: Request,
    processing_queue_controller: ProcessingQueueController = Depends(depends.get_processing_queue_controller),
):
    return processing_queue_controller.summary_pipeline_home(request)
