from fastapi import Request
from fastapi.templating import Jinja2Templates


class ActionCenterController:
    def __init__(self, template_path: str, auth_enabled: bool = False):
        self._templates = Jinja2Templates(directory=template_path)
        self._auth_enabled = auth_enabled

    def action_center_home(self, request: Request):
        return self._templates.TemplateResponse(
            request=request,
            name="dashboard/action_center.html",
            context={"active_page": "action_center", "auth_enabled": self._auth_enabled},
        )
