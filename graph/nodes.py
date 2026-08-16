"""The four LLM agents (Researcher, Writer, Editor, Formatter) + Promo agent.

Anti-hallucination design:
- Only the Researcher touches the outside world (live search).
- The Writer must tag every claim with a fact id like [F3]; anything it cannot
  tag it may not say. The Editor verifies tags against the notes and the
  Formatter strips them from the final Markdown.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from .state import NewsletterState

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
BRAND = "Nawader Coffee — in Arabic ALWAYS exactly «نوادر كافية» (a specialty coffee brand)"

BRAND_AR = "نوادر كافية"
_BRAND_FIX_RE = re.compile(
    r"(?:نوادر|نوايدر|ناوادر|نوادير)\s*(?:كافيه|كافية|كوفي|قهوة)"
    r"|(?:نوايدر|ناوادر|نوادير)"
)


def normalize_brand(text: str) -> str:
    """Rewrite any brand-name variant/misspelling to the canonical form."""
    return _BRAND_FIX_RE.sub(BRAND_AR, text)


class ResearchError(Exception):
    """Raised when the live search yields nothing usable after retries."""


def _llm(temperature: float) -> ChatGroq:
    return ChatGroq(model=GROQ_MODEL, temperature=temperature)


def _event(state: NewsletterState, agent: str, summary: str) -> List[Dict[str, Any]]:
    return list(state.get("events", [])) + [
        {"agent": agent, "summary": summary, "time": time.strftime("%H:%M:%S")}
    ]


def _extract_json(text: str) -> Dict[str, Any]:
    """Parse a JSON object out of an LLM reply, tolerating extra prose/fences."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


# --------------------------------------------------------------------------
# Live search (Researcher's tool)
# --------------------------------------------------------------------------

def _search_tavily(query: str, max_results: int) -> List[Dict[str, str]]:
    from tavily import TavilyClient  # optional dependency

    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    response = client.search(query=query, max_results=max_results)
    return [
        {"title": r.get("title", ""), "snippet": r.get("content", ""), "url": r.get("url", "")}
        for r in response.get("results", [])
    ]


def _search_duckduckgo(query: str, max_results: int) -> List[Dict[str, str]]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        return [
            {"title": r.get("title", ""), "snippet": r.get("body", ""), "url": r.get("href", "")}
            for r in ddgs.text(query, max_results=max_results)
        ]


def run_live_search(topic: str, max_results: int = 8) -> Tuple[List[Dict[str, str]], str]:
    """Try Tavily (if a key is set) then DuckDuckGo, with query fallbacks.

    Returns (results, provider_name). Empty results are handled gracefully:
    we retry with simplified queries before giving up.
    """
    providers = []
    if os.getenv("TAVILY_API_KEY"):
        providers.append(("tavily", _search_tavily))
    providers.append(("duckduckgo", _search_duckduckgo))

    queries = [topic, f"{topic} coffee facts", " ".join(topic.split()[:5])]
    for name, search in providers:
        for query in queries:
            try:
                results = search(query, max_results)
            except Exception:
                break  # provider unavailable — move to the next one
            if results:
                return results, name
    return [], "none"


# --------------------------------------------------------------------------
# Agents
# --------------------------------------------------------------------------

def _parse_fact_lines(text: str) -> List[str]:
    """Extract F#: fact lines, tolerating bullets, bold marks and stray prefixes."""
    notes = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*• ").strip()
        match = re.search(r"F\d+\s*:", line)
        if match and match.start() <= 4:
            notes.append(line[match.start():])
    return notes


def researcher(state: NewsletterState) -> Dict[str, Any]:
    """Runs a live search and distills results into factual bullets F1..Fn."""
    topic = state["topic"]
    results, provider = run_live_search(topic)
    if not results:
        raise ResearchError(
            f"Live search returned no results for topic '{topic}'. "
            "Try a broader topic or check your internet connection."
        )

    raw = "\n\n".join(
        f"SOURCE {i + 1} ({urlparse(r['url']).netloc}):\nTitle: {r['title']}\n{r['snippet']}"
        for i, r in enumerate(results)
    )
    messages = [
        SystemMessage(
            content=(
                "You are a researcher. Report ONLY what the sources say. "
                "Do not write article prose, opinions, or anything not present "
                "in the sources."
            )
        ),
        HumanMessage(
            content=(
                f"Topic: {topic}\n\nSearch results:\n{raw}\n\n"
                "Distill 6-10 short factual bullet points strictly from these "
                "results. Output ONE fact per line in exactly this format:\n"
                "F1: <fact> (source: <domain>)\n"
                "F2: ...\n"
                "No headers, no extra text. Skip anything promotional or vague."
            )
        ),
    ]
    # The model occasionally wraps the facts in prose or another list format;
    # parse leniently, and retry once with a firmer instruction before giving up.
    first_reply = _llm(temperature=0.0).invoke(messages)
    notes = _parse_fact_lines(first_reply.content)
    if not notes:
        messages += [
            first_reply,
            HumanMessage(
                content=(
                    "Your previous reply did not follow the format. Reply again with "
                    "ONLY lines that start with F1:, F2:, F3:, ... — nothing else."
                )
            ),
        ]
        notes = _parse_fact_lines(_llm(temperature=0.0).invoke(messages).content)
    if not notes:
        raise ResearchError("Search succeeded but no verifiable facts could be distilled.")

    return {
        "research_notes": notes,
        "sources": [{"title": r["title"], "url": r["url"]} for r in results],
        "search_provider": provider,
        "events": _event(
            state, "Researcher", f"{len(notes)} facts distilled from {len(results)} {provider} results"
        ),
    }


def writer(state: NewsletterState) -> Dict[str, Any]:
    """Drafts (or revises) the article using ONLY the research notes."""
    critique = state.get("critique", "")
    facts = "\n".join(state["research_notes"])
    revision = state["revision_count"] + 1

    task = (
        f"Write a ~350-word newsletter article for {BRAND} about: {state['topic']}."
        if not critique
        else (
            "Revise the draft below. Address EVERY point in the editor's critique "
            "while still obeying all rules.\n\n"
            f"PREVIOUS DRAFT:\n{state['current_draft']}\n\n"
            f"EDITOR CRITIQUE:\n{critique}"
        )
    )
    reply = _llm(temperature=0.6).invoke(
        [
            SystemMessage(
                content=(
                    f"You are the newsletter writer for {BRAND}. "
                    "STRICT RULES:\n"
                    "1. Use ONLY the numbered facts provided. Never invent names, "
                    "numbers, dates, quotes, or studies.\n"
                    "2. Tag every factual claim with its fact id, e.g. 'Arabica "
                    "dominates world production [F2].' A sentence you cannot tag "
                    "must be generic connective prose, not a claim.\n"
                    "3. Keep the tone warm, neutral and newsworthy — informative "
                    "marketing, not hype.\n"
                    "4. If a critique is present, address every point in it.\n"
                    "5. CRITICAL: Nawader Coffee is the PUBLISHER of this newsletter, "
                    "not a subject of the facts. NEVER claim that Nawader sells, "
                    "offers, launches, or stocks any product, capsule, pack, size, "
                    "or price unless a numbered fact explicitly mentions Nawader. "
                    "Connect to the brand only with framing like 'from your friends "
                    "at Nawader' or an invitation to visit — no product claims.\n"
                    "6. Write the article in the same language as the topic "
                    "(Arabic topic → Arabic article).\n"
                    "7. Brand spelling: in Arabic ALWAYS write the brand exactly as "
                    "«نوادر كافية» — never نوايدر, ناوادر, نوادير, or نوادر كوفي. "
                    "In English: 'Nawader Coffee'."
                )
            ),
            HumanMessage(content=f"FACTS (only allowed source):\n{facts}\n\n{task}"),
        ]
    )
    draft = normalize_brand(reply.content.strip())
    history = list(state.get("draft_history", [])) + [
        {"revision": revision, "draft": draft, "critique_addressed": critique}
    ]
    return {
        "current_draft": draft,
        "revision_count": revision,
        "draft_history": history,
        "events": _event(
            state,
            "Writer",
            f"draft #{revision} written" + (" (revision addressing critique)" if critique else ""),
        ),
    }


# --- Deterministic anti-hallucination verifier (no LLM involved) -----------
# Catches the worst failure mode: the Writer inventing claims about Nawader's
# own products (e.g. "Nawader sells decaf capsules in packs of 10 / 85g"),
# which generic web research can never support.

_BRAND_RE = re.compile(r"nawader|نوادر|نوايدر|ناوادر|نوادير", re.IGNORECASE)
_COMMERCIAL_RE = re.compile(
    r"توفر|تُوفر|تقدم|تقدّم|تبيع|تطرح|تطلق|أطلقت|لدينا|منتجات|عبوات|كبسولات|"
    r"سعر|أسعار|ريال|متجر|"
    r"offers?|sells?|provides?|stocks?|launch(?:es|ed)?|prices?|packs?|capsules?|store",
    re.IGNORECASE,
)
_DIGIT_RE = re.compile(r"[0-9٠-٩]")
_FACT_TAG_RE = re.compile(r"\[F\d+")


def verify_draft(draft: str, notes: List[str]) -> List[str]:
    """Return a list of unsupported-claim issues found mechanically in the draft."""
    brand_in_facts = any(_BRAND_RE.search(note) for note in notes)
    issues: List[str] = []
    for sentence in re.split(r"(?<=[.!؟?])\s+|\n+", draft):
        s = sentence.strip()
        if not s or s.startswith("#"):
            continue
        if _BRAND_RE.search(s) and _COMMERCIAL_RE.search(s) and not brand_in_facts:
            issues.append(
                "ادعاء تجاري عن نوادر غير مدعوم بأي حقيقة بحثية — احذفه أو حوّله لدعوة عامة "
                f"(unsupported Nawader product claim): «{s[:150]}»"
            )
        elif _DIGIT_RE.search(s) and not _FACT_TAG_RE.search(s):
            issues.append(
                "جملة تحتوي أرقاماً بدون وسم حقيقة [F#] "
                f"(numeric claim missing a fact tag): «{s[:150]}»"
            )
    return issues


def editor(state: NewsletterState) -> Dict[str, Any]:
    """Judges the draft against the notes; returns verdict + actionable critique."""
    reply = _llm(temperature=0.0).invoke(
        [
            SystemMessage(
                content=(
                    "You are a strict editor-in-chief. Give specific, actionable "
                    "feedback. Judge ONLY against the provided facts."
                )
            ),
            HumanMessage(
                content=(
                    f"FACTS:\n{chr(10).join(state['research_notes'])}\n\n"
                    f"DRAFT:\n{state['current_draft']}\n\n"
                    "Evaluate the draft on three axes:\n"
                    "1. factual_grounding — is every [F#]-tagged claim truly supported "
                    "by that fact, with no untagged/hallucinated claims?\n"
                    "2. tone — neutral and newsworthy, not hype?\n"
                    "3. brand_relevance — judge the SUBJECT itself: is the topic "
                    "genuinely about coffee, cafés, or café lifestyle? Wrapper "
                    "phrases like 'from your friends at Nawader' do NOT make an "
                    "unrelated topic (a programming language, politics, sports...) "
                    "relevant — score such topics 3 or lower and REJECT, telling "
                    "the writer to build a real coffee angle from the facts or "
                    "state that none exists.\n\n"
                    "HARD RULE: the draft must NOT attribute any product, price, "
                    "pack, size, offer, or capability to Nawader Coffee itself "
                    "unless a fact explicitly mentions Nawader — the facts come "
                    "from general web research, so such claims are fabrications. "
                    "REJECT immediately if you find one.\n\n"
                    "Reply with ONLY a JSON object, no markdown fences:\n"
                    '{"status": "APPROVED" or "REJECTED", '
                    '"critique": "<specific actionable feedback; empty if approved>", '
                    '"scores": {"factual_grounding": 1-10, "tone": 1-10, '
                    '"brand_relevance": 1-10}}\n'
                    "Reject if any score is below 7 or any claim is unsupported."
                )
            ),
        ]
    )
    parsed = _extract_json(reply.content)
    status = str(parsed.get("status", "")).upper()
    if status not in ("APPROVED", "REJECTED"):
        status = "APPROVED" if "APPROVED" in reply.content.upper() else "REJECTED"
    critique = parsed.get("critique", "") or (
        "" if status == "APPROVED" else "The draft needs tighter fact grounding."
    )
    scores = parsed.get("scores", {}) or {}

    # Deterministic layer: mechanical check overrides a lenient LLM verdict.
    machine_issues = verify_draft(state["current_draft"], state["research_notes"])
    if machine_issues:
        status = "REJECTED"
        critique = (
            (critique + "\n\n" if critique else "")
            + "فحص آلي (automated verifier) — صحّح كل نقطة:\n- "
            + "\n- ".join(machine_issues)
        )

    # Test hook: force rejection to demonstrate the revision-cap safety exit.
    if state.get("demo_force_reject"):
        status = "REJECTED"
        critique = (
            "[demo forced rejection] "
            + (critique or "Tighten the intro and ground every claim in a tagged fact.")
        )

    return {
        "status": status,
        "critique": critique if status == "REJECTED" else "",
        "editor_scores": {k: int(v) for k, v in scores.items() if str(v).isdigit()},
        "events": _event(state, "Editor", f"verdict: {status}" + (f" — {critique[:80]}" if critique else "")),
    }


def formatter(state: NewsletterState) -> Dict[str, Any]:
    """Turns the approved/capped draft into clean Markdown. Formatting only."""
    reply = _llm(temperature=0.2).invoke(
        [
            SystemMessage(
                content=(
                    "You are a Markdown formatter. Improve structure and readability "
                    "ONLY: one # headline, ## sub-headings, short paragraphs, maybe a "
                    "bullet list. NEVER add, remove, or change facts or meaning. "
                    "Remove the [F#] citation tags from the text."
                )
            ),
            HumanMessage(content=f"Format this article:\n\n{state['current_draft']}"),
        ]
    )
    markdown = re.sub(r"\s*\[F\d+(?:\s*,\s*F\d+)*\]", "", reply.content.strip())
    markdown = normalize_brand(markdown)
    return {
        "article_markdown": markdown,
        "events": _event(state, "Formatter", "final Markdown produced"),
    }


def promoter(state: NewsletterState) -> Dict[str, Any]:
    """builds a social-media promo pack from the FINAL article."""
    if not state.get("include_promo", True):
        return {"events": _event(state, "Promoter", "skipped (disabled)")}

    reply = _llm(temperature=0.7).invoke(
        [
            SystemMessage(
                content=(
                    f"You are the social media manager of {BRAND}. Create short promo "
                    "posts strictly based on the article — no new facts, and NEVER "
                    "invent Nawader products, prices, or offers. Write in the same "
                    "language as the article."
                )
            ),
            HumanMessage(
                content=(
                    f"ARTICLE:\n{state['article_markdown']}\n\n"
                    "Reply with ONLY a JSON object:\n"
                    '{"tweet": "<=280 chars, 1-2 fitting hashtags", '
                    '"instagram": "2-3 warm sentences + emoji + hashtags", '
                    '"tiktok": "a short playful video caption + emoji + hashtags"}'
                )
            ),
        ]
    )
    pack = _extract_json(reply.content)
    return {
        "promo_pack": {k: normalize_brand(str(v)) for k, v in pack.items()},
        "events": _event(state, "Promoter", "social-media promo pack ready"),
    }
