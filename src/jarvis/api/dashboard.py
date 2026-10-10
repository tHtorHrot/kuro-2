"""Read-only task dashboard (static page; data calls carry the operator token)."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/dashboard", include_in_schema=False)
async def dashboard():
    return FileResponse(Path(__file__).with_name("dashboard.html"), media_type="text/html")
