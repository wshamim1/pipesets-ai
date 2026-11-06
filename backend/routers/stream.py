"""
Streaming run endpoint — POST /api/run/stream

SSE event types (unchanged — frontend contract is stable):
  {"type": "token",    "text": "..."}
  {"type": "thought",  "text": "..."}
  {"type": "tool_call","name":"...","input":"..."}
  {"type": "tool",     "name":"...","output":"..."}
  {"type": "step",     "step": N}
  {"type": "meta",     "provider":"...","model":"...","usage":{...},"cost_usd":N,"steps":N}
  {"type": "done"}
  {"type": "error",    "message": "..."}
  {"type": "run",      "run_id":"...","resumed_steps":N}   (checkpointed runs, first)

A request with ``run_id`` is checkpointed (services/llm_checkpoint.py); re-sending it with
``resume_from`` instead continues an interrupted or failed run from its last finished step.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from models import PromptRunRequest
from services import llm_checkpoint
from services.llm_runner import run_stream

router = APIRouter(tags=["stream"])


@router.post("/api/run/stream")
async def stream_endpoint(req: PromptRunRequest):
    # Claimed before streaming starts, so a run that can't start or resume is a real HTTP error
    cp = None
    try:
        if req.resume_from:
            cp = llm_checkpoint.claim(req)
        elif req.run_id:
            cp = llm_checkpoint.start(req)
    except llm_checkpoint.NotResumable as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return StreamingResponse(
        run_stream(req, cp),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
