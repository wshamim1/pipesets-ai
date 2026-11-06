"""release_notes.py — GET /api/release-notes?limit=1: what was released in the latest commit(s), for the
"What's new" panel (services/release_notes.py). Any signed-in user."""

from fastapi import APIRouter, Request

from services import release_notes
from services.request_context import get_request_context

router = APIRouter(prefix="/api/release-notes", tags=["release-notes"])


@router.get("")
def get_release_notes(request: Request, limit: int = 1):
    get_request_context(request)   # signed in
    return release_notes.latest(limit)
