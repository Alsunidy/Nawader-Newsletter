"""Nawader Newsletter — Arabic Streamlit UI (a form, not a chat).

Talks to the FastAPI backend over HTTP only (never imports the graph).
Uses the SSE streaming endpoint to show each agent working live, with an
automatic fallback to the plain endpoint if streaming fails.
"""
import json
import os
import random

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="فريق نشرة نوادر كافية", page_icon="☕", layout="wide")

# Right-to-left (RTL) support for every UI element
st.markdown(
    """
    <style>
    html, body, .stApp, [data-testid="stAppViewContainer"],
    .block-container, [data-testid="stVerticalBlock"] {
        direction: rtl;
    }
    /* text, headings, paragraphs and lists */
    .stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown blockquote,
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4,
    h1, h2, h3, [data-testid="stCaptionContainer"],
    [data-testid="stAlert"], [data-testid="stAlertContentInfo"] {
        direction: rtl; text-align: right;
    }
    .stMarkdown ul, .stMarkdown ol {
        direction: rtl; text-align: right;
        padding-right: 1.6rem; padding-left: 0; margin-right: 0;
    }
    /* inputs, labels and toggles */
    [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p,
    .stTextInput label, .stCheckbox label, [data-testid="stToggle"] label {
        direction: rtl; text-align: right;
    }
    .stTextInput input, .stTextArea textarea {
        direction: rtl; text-align: right;
    }
    /* metrics */
    [data-testid="stMetric"] {
        direction: rtl; text-align: right;
    }
    [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {
        direction: rtl; text-align: right; width: 100%;
    }
    [data-testid="stMetricValue"] {
        direction: ltr; text-align: right; width: 100%;
    }
    /* expanders, status box and tabs */
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] summary p,
    [data-testid="stExpanderDetails"] {
        direction: rtl; text-align: right;
    }
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        direction: rtl; justify-content: flex-start;
    }
    /* code blocks (Arabic promo posts) */
    [data-testid="stCode"] pre, [data-testid="stCode"] code, .stCode pre {
        direction: rtl; text-align: right; white-space: pre-wrap;
    }
    /* buttons */
    [data-testid="stDownloadButton"], .stButton, .stFormSubmitButton {
        direction: rtl;
    }
    /* toggles: the label stays RTL but the switch body must stay LTR,
       otherwise the white knob renders outside the track
       (st.toggle renders as stCheckbox) */
    [data-testid="stCheckbox"] label { direction: rtl; }
    [data-testid="stCheckbox"] label > div:first-of-type {
        direction: ltr !important;
    }
    /* hide the "Press Enter to submit form" hint */
    [data-testid="InputInstructions"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("فريق نشرة نوادر كافية البريدية")
st.caption(
    "اكتب موضوعاً وشاهد الفريق يعمل."
)

AGENTS = {
    "Researcher": ("🔎", "الباحث"),
    "Writer": ("✍️", "الكاتب"),
    "Editor": ("🧐", "المحرر"),
    "Formatter": ("📄", "المنسّق"),
    "Promoter": ("📣", "المسوّق"),
}


def agent_label(name: str) -> str:
    icon, arabic = AGENTS.get(name, ("🤖", name))
    return f"{icon} **{arabic}**"


def call_api_streaming(payload: dict, status_box) -> dict | None:
    """Consume the SSE endpoint, updating the status box on every agent step."""
    response = requests.post(
        f"{API_URL}/get_article/stream", json=payload, stream=True, timeout=600
    )
    response.raise_for_status()
    result, event_type = None, ""
    for raw in response.iter_lines(decode_unicode=True):
        if not raw:
            continue
        if raw.startswith("event:"):
            event_type = raw.split(":", 1)[1].strip()
        elif raw.startswith("data:"):
            data = json.loads(raw.split(":", 1)[1].strip())
            if event_type == "progress":
                status_box.write(f"{agent_label(data['agent'])} — {data['summary']}")
            elif event_type == "result":
                result = data
            elif event_type == "error":
                raise RuntimeError(data["error"])
    return result


def call_api_sync(payload: dict) -> dict:
    response = requests.post(f"{API_URL}/get_article", json=payload, timeout=600)
    if response.status_code != 200:
        detail = response.json().get("detail", {})
        raise RuntimeError(detail.get("error", response.text) if isinstance(detail, dict) else detail)
    return response.json()


# ------------------- Rotating topic suggestions ---------------------------
TOPIC_POOL = [
    "جودة القهوة المختصة ومعاييرها",
    "القهوة منزوعة الكافيين وعلم الكافيين",
    "الفرق بين حبوب أرابيكا وروبوستا",
    "تاريخ القهوة السعودية والهيل",
    "طرق تحميص البن ودرجاته",
    "القهوة الباردة (كولد برو) وطريقة تحضيرها",
    "تأثير القهوة على النوم والتركيز",
    "فن اللاتيه آرت وأساسياته",
    "زراعة البن في إثيوبيا واليمن",
    "التخمير اليدوي: V60 والكيمكس",
    "القهوة والرياضة: الكافيين قبل التمرين",
    "طريقة تخزين البن للحفاظ على النكهة",
    "أهمية جودة الماء في تحضير القهوة",
    "القهوة التركية وتراثها",
    "يوم القهوة العالمي وفعالياته",
    "درجات طحن القهوة وتأثيرها على المذاق",
    "موجات القهوة الثلاث: من التقليدية إلى المختصة",
    "فوائد القهوة الصحية بحسب الدراسات",
    "الإسبريسو: تاريخه وطريقة إتقانه",
    "مهرجانات القهوة في السعودية",
]

if "suggestions" not in st.session_state:
    st.session_state["suggestions"] = random.sample(TOPIC_POOL, 3)

st.markdown("**💡 اقتراحات لمواضيع اليوم** — اضغط اقتراحاً ليبدأ العمل فوراً:")
sugg_cols = st.columns([1, 5, 5, 5])
if sugg_cols[0].button("🎲", help="اقتراحات جديدة", use_container_width=True):
    st.session_state["suggestions"] = random.sample(TOPIC_POOL, 3)
    st.rerun()

clicked_topic = None
for i, suggestion in enumerate(st.session_state["suggestions"]):
    if sugg_cols[i + 1].button(suggestion, key=f"sugg_{i}", use_container_width=True):
        clicked_topic = suggestion

if clicked_topic:
    # pre-fill the topic field before the form renders
    st.session_state["topic_input"] = clicked_topic

# ----------------------------- Input form ---------------------------------
opt1, opt2 = st.columns(2)
include_promo = opt1.toggle("توليد منشورات تواصل اجتماعي", value=True)
demo_force_reject = opt2.toggle(
    "وضع تجريبي: رفض إجباري (لعرض حد الأمان)", value=False,
    help="المحرر يرفض كل مسودة حتى تشاهد الحلقة تصل إلى حد المراجعات (3) وتخرج إجبارياً.",
)

with st.form("topic_form"):
    topic = st.text_input(
        "موضوع المقال",
        key="topic_input",
        placeholder="مثال: جودة القهوة المختصة ومعاييرها",
    )
    submitted = st.form_submit_button("✨ توليد المقال", type="primary", use_container_width=True)

run_topic = ""
if submitted:
    if not topic.strip():
        st.error("رجاءً أدخل موضوعاً أولاً.")
        st.stop()
    run_topic = topic.strip()
elif clicked_topic:
    run_topic = clicked_topic

if run_topic:
    payload = {
        "topic": run_topic,
        "include_promo": include_promo,
        "demo_force_reject": demo_force_reject,
    }
    result = None
    with st.status("فريق التحرير يعمل الآن…", expanded=True) as status_box:
        try:
            result = call_api_streaming(payload, status_box)
            status_box.update(label="اكتمل العمل! ✅", state="complete", expanded=False)
        except RuntimeError as exc:  # workflow-level error (e.g. empty search)
            status_box.update(label="فشل سير العمل", state="error")
            st.error(f"⚠️ {exc}")
            st.stop()
        except requests.RequestException:
            status_box.write("البث غير متاح — سيتم استخدام طلب عادي…")
            try:
                result = call_api_sync(payload)
                status_box.update(label="اكتمل العمل! ✅", state="complete", expanded=False)
            except (requests.RequestException, RuntimeError) as exc:
                status_box.update(label="تعذر الوصول إلى الخادم", state="error")
                st.error(f"تعذر الوصول إلى الخادم على {API_URL}. هل uvicorn يعمل؟\n\n{exc}")
                st.stop()
    st.session_state["result"] = result
    # fresh suggestions for the next round
    st.session_state["suggestions"] = random.sample(TOPIC_POOL, 3)

# ----------------------------- Results ------------------------------------
result = st.session_state.get("result")
if result:
    approved = result["final_status"] == "APPROVED"

    # status row: verdict, draft count, editor rubric scores
    cols = st.columns(4)
    cols[0].metric("قرار المحرر", "✅ معتمد" if approved else "⛔ حد الأمان")
    cols[1].metric("عدد المسودات", result["revision_count"])
    scores = result.get("editor_scores", {})
    cols[2].metric("الدقة الواقعية", f"{scores.get('factual_grounding', '—')}/10")
    cols[3].metric("الأسلوب · العلامة", f"{scores.get('tone', '—')} · {scores.get('brand_relevance', '—')}")

    if not approved:
        st.warning(
            "المحرر لم يعتمد أي مسودة — حد الأمان (3 مسودات) أنهى الحلقة إجبارياً "
            "وتم تنسيق أفضل مسودة متاحة."
        )

    article_tab, promo_tab = st.tabs(["📰 المقال", "📣 منشورات ترويجية"])
    with article_tab:
        st.markdown(result["article_markdown"])
        st.download_button(
            "⬇️ تحميل المقال (Markdown)",
            result["article_markdown"],
            file_name="nawader_newsletter.md",
            mime="text/markdown",
        )
    with promo_tab:
        promo = result.get("promo_pack", {})
        channels = {"tweet": "منشور X (تويتر)", "instagram": "انستقرام", "tiktok": "تيك توك"}
        if promo:
            for key, label in channels.items():
                if promo.get(key):
                    st.subheader(label)
                    st.code(promo[key], language=None)
        else:
            st.info("توليد المنشورات كان معطلاً في هذا التشغيل.")

    # -------------------- Behind the scenes: the reflection loop -----------
    st.divider()
    st.subheader("🔍 خلف الكواليس (حلقة المراجعة)")

    provider = result.get("search_provider", "؟")
    with st.expander(f"ملاحظات البحث ({len(result['research_notes'])}) — عبر {provider}"):
        for note in result["research_notes"]:
            st.markdown(f"- {note}")
        if result.get("sources"):
            st.caption("المصادر: " + " · ".join(f"[{s['title'][:40]}]({s['url']})" for s in result["sources"][:6]))

    with st.expander("آخر ملاحظات المحرر (النقد)"):
        st.write(result["final_critique"] or "لا توجد ملاحظات متبقية — المسودة اعتُمدت. ✅")

    with st.expander("سجل المسودات (قبل / بعد كل نقد)"):
        for entry in result.get("draft_history", []):
            st.markdown(f"**المسودة رقم {entry['revision']}**")
            if entry["critique_addressed"]:
                st.info(f"النقد الذي عالجته هذه المسودة: {entry['critique_addressed']}")
            st.text_area(
                f"draft_{entry['revision']}", entry["draft"], height=180,
                label_visibility="collapsed", disabled=True,
            )

    with st.expander("الخط الزمني لعمل الوكلاء"):
        for event in result.get("events", []):
            st.markdown(f"`{event['time']}` {agent_label(event['agent'])} — {event['summary']}")
