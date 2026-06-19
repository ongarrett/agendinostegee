from fastapi import Request
from fastapi.templating import Jinja2Templates


class ProcessingQueueController:
    def __init__(self, template_path: str, auth_enabled: bool = False):
        self._templates = Jinja2Templates(directory=template_path)
        self._auth_enabled = auth_enabled

    def processing_queue_home(self, request: Request):
        return self._templates.TemplateResponse(
            request=request,
            name="dashboard/processing_queue.html",
            context={"active_page": "processing_queue", "auth_enabled": self._auth_enabled},
        )
