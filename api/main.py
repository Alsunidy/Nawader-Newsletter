"""FastAPI backend serving the pre-compiled LangGraph newsletter workflow.

Endpoints:
- POST /get_article          — run the full workflow, return the final state.
- POST /get_article/stream   — same, but streams agent progress live (SSE).
- GET  /health               — liveness probe.
"""
import json
from typing import Any, Dict

from dotenv import load_dotenv

load_dotenv()  # must run before the graph (and ChatGroq) is imported

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from graph import initial_state, newsletter_graph  # noqa: E402  (pre-compiled once)
from graph.nodes import ResearchError  # noqa: E402
from graph.router import final_status  # noqa: E402

app = FastAPI(
    title="Nawader Newsletter Team",
    description="Multi-agent newsletter writer (LangGraph): research → write → edit ⇄ revise → format.",
    version="1.0.0",
)


class ArticleRequest(BaseModel):
    topic: str = Field(..., description="Subject of the newsletter article")
    demo_force_reject: bool = Field(
        False, description="Test hook: Editor always rejects, to demo the revision cap"
    )
    include_promo: bool = Field(True, description="Also generate the social-media promo pack")


def _validate(request: ArticleRequest) -> None:
    if not request.topic or not request.topic.strip():
        raise HTTPException(status_code=400, detail={"error": "topic must be a non-empty string"})


def _response_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "article_markdown": state.get("article_markdown", ""),
        "research_notes": state.get("research_notes", []),
        "revision_count": state.get("revision_count", 0),
        "final_status": final_status(state),
        "final_critique": state.get("critique", ""),
        # innovation extras
        "editor_scores": state.get("editor_scores", {}),
        "search_provider": state.get("search_provider", ""),
        "sources": state.get("sources", []),
        "draft_history": state.get("draft_history", []),
        "promo_pack": state.get("promo_pack", {}),
        "events": state.get("events", []),
    }


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/get_article")
def get_article(request: ArticleRequest) -> Dict[str, Any]:
    _validate(request)
    state = initial_state(request.topic, request.demo_force_reject, request.include_promo)
    try:
        final = newsletter_graph.invoke(state)
    except ResearchError as exc:
        raise HTTPException(status_code=424, detail={"error": str(exc)})
    return _response_payload(final)


@app.post("/get_article/stream")
def get_article_stream(request: ArticleRequest) -> StreamingResponse:
    """Server-Sent Events: one `progress` event per agent step, then `result`."""
    _validate(request)
    state = initial_state(request.topic, request.demo_force_reject, request.include_promo)

    def event_stream():
        final: Dict[str, Any] = {}
        try:
            for step in newsletter_graph.stream(state, stream_mode="values"):
                final = step
                events = step.get("events", [])
                if events:
                    yield f"event: progress\ndata: {json.dumps(events[-1])}\n\n"
            yield f"event: result\ndata: {json.dumps(_response_payload(final))}\n\n"
        except ResearchError as exc:
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
