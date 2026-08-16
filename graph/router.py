"""Conditional routing after the Editor — plain Python, no LLM.

revision_count counts drafts the Writer has produced (draft #1 = 1).
The safety cap guarantees termination: after MAX_REVISIONS drafts the
workflow force-exits to the Formatter with the best draft so far, and the
API reports final_status = REVISION_CAP_REACHED instead of APPROVED.
"""
from typing import Literal

from .state import NewsletterState

MAX_REVISIONS = 3


def route_after_editor(state: NewsletterState) -> Literal["writer", "formatter"]:
    if state["status"] == "APPROVED":
        return "formatter"
    if state["revision_count"] >= MAX_REVISIONS:
        return "formatter"  # safety cap — force exit with the best draft so far
    return "writer"  # REJECTED and under the cap: revise with the critique


def final_status(state: NewsletterState) -> str:
    """What the API reports: genuine approval vs. forced exit."""
    if state["status"] == "APPROVED":
        return "APPROVED"
    return "REVISION_CAP_REACHED"
