# ☕ Nawader Newsletter Team — Multi-Agent Writer with LangGraph

A team of specialist AI agents that turns a topic into a fact-checked, publish-ready
newsletter article for **Nawader Coffee**:

```
User topic
   │
   ▼
🔎 Researcher ──► ✍️ Writer ──► 🧐 Editor ──► Router ──APPROVED──► 📄 Formatter ──► 📣 Promoter ──► END
   (live search)      ▲                          │                      (final Markdown)   (social posts)
                      └────── REJECTED ◄─────────┘
                        critique + revision_count < 3
                        (safety cap forces exit at 3)
```

The **reflection loop** is the heart of the system: the Editor rejects weak drafts
with a specific critique, the Writer revises to address every point, and a plain-Python
Router decides whether to loop again, until approval or the safety cap (3 drafts).

---

## How to run

### 1. Setup

```bash
cd nawader-newsletter
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # then put your real GROQ_API_KEY inside
```

You need a free **Groq** key (https://console.groq.com/keys). A **Tavily** key is
optional — without it the Researcher automatically uses DuckDuckGo (no key needed).

### 2. Start the API (terminal 1)

```bash
uvicorn api.main:app --reload
# → http://127.0.0.1:8000  (interactive docs at /docs)
```

### 3. Start the UI (terminal 2)

```bash
streamlit run streamlit_app.py
# → http://localhost:8501
```

Type a topic, press **Generate article**, and watch the agents work live.

### API example

```bash
curl -X POST http://127.0.0.1:8000/get_article \
  -H "Content-Type: application/json" \
  -d "{\"topic\": \"Specialty coffee quality and standards\"}"
```

Response shape:

```json
{
  "article_markdown": "# ...",
  "research_notes": ["F1: ...", "F2: ..."],
  "revision_count": 2,
  "final_status": "APPROVED",            // or "REVISION_CAP_REACHED"
  "final_critique": "",
  "editor_scores": {"factual_grounding": 9, "tone": 8, "brand_relevance": 8},
  "search_provider": "duckduckgo",
  "sources": [...], "draft_history": [...], "promo_pack": {...}, "events": [...]
}
```

Errors: empty topic → **HTTP 400**; live search finds nothing → **HTTP 424** with a
clear JSON message. The graph is compiled **once at import** and reused per request.

---

## The agents

| Agent | Reads | Writes | Special rule |
|---|---|---|---|
| **Researcher** | `topic` | `research_notes` | Only node allowed outside info; must call a real search tool (Tavily → DuckDuckGo fallback, query-simplification retries, graceful empty handling). |
| **Writer** | `topic`, `research_notes`, `critique` | `current_draft`, `revision_count` | Uses ONLY the provided facts; must tag every claim with its fact id `[F#]`. |
| **Editor** | `current_draft`, `research_notes` | `status`, `critique` | Strict JSON verdict + a 3-axis rubric (grounding / tone / brand, 1-10); rejects if any axis < 7. |
| **Router** | `status`, `revision_count` | — (plain Python) | APPROVED → Formatter; REJECTED & count < 3 → Writer; count == 3 → force-exit (API flags `REVISION_CAP_REACHED`). |
| **Formatter** | `current_draft` | `article_markdown` | Structure/readability only; strips the `[F#]` tags; never changes meaning. |
| **Promoter** (bonus) | `article_markdown` | `promo_pack` | X (Twitter) + Instagram + TikTok posts grounded strictly in the final article, in the article's language. |

**Shared state** ([graph/state.py](graph/state.py)): the six required fields are a strict
`TypedDict` (`topic`, `research_notes`, `current_draft`, `critique`, `status: Literal`,
`revision_count`), extended with optional observability fields.

---

## The UI (Arabic, RTL)

A form, not a chat — reachable only through HTTP calls to the API:

- **One topic field + a "توليد المقال" button**, plus two toggles (promo pack on/off,
  and the force-reject demo used for the safety-cap test case).
- **💡 Rotating suggestions**: three random topic chips from a curated Arabic
  coffee-topic pool; clicking one fills the field and starts the pipeline immediately.
  🎲 reshuffles, and a new batch is drawn after every article.
- **Live progress**: while generating, an `st.status` panel streams each agent's step
  (🔎 الباحث → ✍️ الكاتب → 🧐 المحرر → 📄 المنسّق → 📣 المسوّق) over SSE.
- **Status row**: Editor verdict (✅ approved / ⛔ cap reached), number of drafts, and
  the Editor's rubric scores.
- **Output tabs**: the rendered article (`st.markdown` + a Markdown download button)
  and the social-media promo pack.
- **"Behind the scenes" expanders** (the graded observability): research notes with
  source links and the search provider used, the final critique, the full draft history
  (each draft next to the critique it addressed), and the agent timeline.

## Required test cases

Reproduce all evidence automatically: start the API, then

```bash
python scripts/run_test_cases.py
```

It verifies the empty-topic → 400 edge case and writes full evidence (notes, every
draft, critiques, final article) to `tests_evidence/*.md`:

1. **Clean run** — `tests_evidence/1_clean_run.md`: approved within 1–2 drafts, with
   final article and `revision_count`.
2. **Revision in action** — `tests_evidence/2_revision_in_action.md`: shows a rejected
   draft, the Editor's concrete critique, and the improved draft that addressed it
   (before/after visible in `draft_history`).
3. **Safety cap** — `tests_evidence/3_safety_cap.md`: run with `demo_force_reject: true`
   so the Editor rejects every draft; the run terminates at `revision_count == 3` with
   `final_status = "REVISION_CAP_REACHED"`, proving the workflow always ends.

The same three scenarios can be shown live in the UI (the safety-cap demo is the
"force rejections" toggle).

---

## 💡 Innovation features

1. **Live agent streaming (SSE)** — `POST /get_article/stream` emits a progress event
   per agent step; the Streamlit `st.status` panel shows the team working in real time
   instead of a frozen spinner.
2. **Fact-tagging guardrail** — the Writer must cite `[F#]` for every claim, the Editor
   verifies tags against the notes, and the Formatter strips them. Hallucinations
   become *mechanically detectable*, not just "judged".
3. **Deterministic anti-hallucination verifier (no LLM)** — `verify_draft()` in
   [graph/nodes.py](graph/nodes.py) mechanically scans every sentence and force-rejects
   drafts that (a) attribute products/prices/packs to Nawader itself when no research
   fact mentions Nawader (the classic "Nawader sells decaf capsules, 10-pack, 85g"
   fabrication), or (b) contain numbers with no `[F#]` tag. This overrides a lenient
   Editor verdict, so the safety net doesn't depend on the LLM being careful.
4. **Brand-name canonicalization** — the LLM sometimes misspells the Arabic brand
   name (نوايدر / ناوادر / نوادر كوفي). `normalize_brand()` deterministically rewrites
   every variant to the canonical «نوادر كافية» in the draft, the final article, and
   the promo posts — enforced in code, not just prompted.
5. **Arabic RTL interface** — the Streamlit UI is fully in Arabic with hand-tuned RTL
   CSS (including fixes for Streamlit's LTR-only toggle switch and hiding the English
   "Press Enter to submit" hint); the Writer also answers in the topic's language.
6. **Rotating topic suggestions** — the UI offers three random topic chips from a
   curated Arabic coffee-topic pool; one click fills the field and starts the whole
   pipeline immediately. A 🎲 button reshuffles them, and a fresh batch is drawn after
   every generated article.
7. **Editor rubric scores** — a 3-axis 1–10 rubric (factual grounding / tone / brand
   relevance) returned by the API and shown as metrics in the UI.
8. **Draft history + before/after viewer** — every draft and the critique it addressed
   are kept in state and browsable in an expander, making the reflection loop's value
   visible.
9. **Social-media Promoter agent** — a bonus node that turns the final article into a
   ready-to-post X (Twitter) post, Instagram caption, and TikTok caption (grounded in
   the article only, written in the article's language).
10. **Dual search provider with graceful degradation** — Tavily when a key exists,
    DuckDuckGo otherwise, plus query-simplification retries before failing cleanly (HTTP 424).
11. **Built-in cap demo & test harness** — `demo_force_reject` flag + a one-command
    script that generates all README test evidence, including the empty-topic → 400 check.

---

## Assumptions

- `revision_count` counts **drafts the Writer produced** (first draft = 1), matching
  "the Writer increments revision_count". The cap of 3 therefore means at most
  3 drafts (1 initial + 2 revisions), and the example response's
  `"revision_count": 2` = approved on the 2nd draft.
- The assignment names the route `get_article`; implemented as `POST /get_article`
  (POST because it has a JSON body).
- The Editor's verdict is produced as strict JSON; if parsing ever fails we fall back
  to keyword detection, and an unparseable verdict counts as REJECTED (safer).
- `status` uses `Literal["PENDING", "APPROVED", "REJECTED"]` — `PENDING` is the value
  before the Editor has ever run.
- Groq model defaults to `llama-3.3-70b-versatile` (override with `GROQ_MODEL`).
- The brand's canonical Arabic name is «نوادر كافية»; any variant the LLM produces
  (نوايدر، ناوادر، نوادر كوفي…) is rewritten to it deterministically in code.
- The UI is in Arabic (RTL) since Nawader's newsletter audience is Arabic-speaking;
  articles follow the language of the topic entered.
- The promo pack targets X (Twitter), Instagram, and TikTok — the channels most
  relevant to a specialty-coffee audience.
- **Off-brand topics** (e.g. "the Python programming language"): the Editor's
  brand-relevance axis judges the *subject itself* — wrapper phrases like "from your
  friends at Nawader" don't make an unrelated topic relevant. Such topics are rejected
  with a critique asking for a genuine coffee angle; if none can be built from the
  facts, the run exits via the safety cap flagged `REVISION_CAP_REACHED`, so the human
  reviewer can see it was never genuinely approved.
- The Researcher's fact distillation parses the model's `F#:` lines leniently
  (bullets/bold tolerated) and retries once with a firmer instruction before failing,
  since LLMs occasionally drift from the requested format.

## Project structure

```
nawader-newsletter/
├── graph/
│   ├── state.py          # strict TypedDict shared state
│   ├── nodes.py          # researcher, writer, editor, formatter (+ promoter)
│   ├── router.py         # conditional routing + revision cap (plain Python)
│   └── build_graph.py    # wires nodes/edges, compiles the graph once
├── api/
│   └── main.py           # FastAPI: POST /get_article (+ /stream SSE, /health)
├── streamlit_app.py      # form UI that calls the API over HTTP only
├── scripts/
│   └── run_test_cases.py # generates the README test evidence automatically
├── requirements.txt
├── .env.example
└── README.md
```
