"""Shared state that flows through every node of the newsletter graph.

The six core fields required by the assignment are strictly typed and
required. The extra fields power the innovation features (live timeline,
editor rubric scores, draft history, promo pack) and are optional.
"""
from typing import Any, Dict, List, Literal, TypedDict

Status = Literal["PENDING", "APPROVED", "REJECTED"]


class CoreState(TypedDict):
    """The six required fields — every node reads/writes only these + extras."""

    topic: str                     # user input: the article subject
    research_notes: List[str]      # Researcher: factual bullets, only fact source
    current_draft: str             # Writer: latest article version
    critique: str                  # Editor: feedback the Writer must address
    status: Status                 # Editor verdict; the Router branches on it
    revision_count: int            # Writer: drafts produced; caps the loop


class NewsletterState(CoreState, total=False):
    """Core state plus extra fields"""

    article_markdown: str            # Formatter: final output the API returns
    draft_history: List[Dict[str, Any]]  # every draft + the critique it answered
    editor_scores: Dict[str, int]    # rubric: grounding / tone / brand (1-10)
    search_provider: str             # which live search tool actually ran
    sources: List[Dict[str, str]]    # raw search hits (title + url)
    promo_pack: Dict[str, str]       # social-media snippets built from the article
    events: List[Dict[str, Any]]     # timeline of agent actions (observability)
    demo_force_reject: bool          # test hook: Editor always rejects (cap demo)
    include_promo: bool              # toggle the bonus social-media node


def initial_state(
    topic: str,
    demo_force_reject: bool = False,
    include_promo: bool = True,
) -> NewsletterState:
    return NewsletterState(
        topic=topic.strip(),
        research_notes=[],
        current_draft="",
        critique="",
        status="PENDING",
        revision_count=0,
        article_markdown="",
        draft_history=[],
        editor_scores={},
        search_provider="",
        sources=[],
        promo_pack={},
        events=[],
        demo_force_reject=demo_force_reject,
        include_promo=include_promo,
    )
