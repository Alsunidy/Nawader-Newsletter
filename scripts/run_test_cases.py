"""Runs the three required test cases against the running API and saves the
evidence as Markdown files under tests_evidence/ (paste them into the README).

Usage:  1) start the API:  uvicorn api.main:app
        2) python scripts/run_test_cases.py
"""
import json
import pathlib
import sys

import requests

API_URL = "http://127.0.0.1:8000"
OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "tests_evidence"

CASES = [
    {
        "name": "1_clean_run",
        "title": "Test 1 — Clean run (approved quickly)",
        "payload": {"topic": "Specialty coffee quality and standards", "include_promo": False},
    },
    {
        "name": "2_revision_in_action",
        "title": "Test 2 — Revision in action (rejected → critique → improved)",
        "payload": {"topic": "Decaf coffee and caffeine science", "include_promo": False},
    },
    {
        "name": "3_safety_cap",
        "title": "Test 3 — Safety cap (forced rejections until revision_count == 3)",
        "payload": {
            "topic": "The history of Arabic coffee",
            "include_promo": False,
            "demo_force_reject": True,
        },
    },
]


def run_case(case: dict) -> str:
    print(f"Running {case['name']} ...")
    response = requests.post(f"{API_URL}/get_article", json=case["payload"], timeout=900)
    response.raise_for_status()
    data = response.json()

    lines = [
        f"## {case['title']}",
        "",
        f"**Topic:** {case['payload']['topic']}",
        f"**final_status:** `{data['final_status']}` · **revision_count:** {data['revision_count']}",
        f"**Editor scores:** `{json.dumps(data.get('editor_scores', {}))}`",
        "",
        "### Research notes",
        *[f"- {note}" for note in data["research_notes"]],
        "",
    ]
    for entry in data.get("draft_history", []):
        lines.append(f"### Draft #{entry['revision']}")
        if entry["critique_addressed"]:
            lines += ["", f"> **Critique addressed:** {entry['critique_addressed']}", ""]
        lines += ["", "```", entry["draft"], "```", ""]
    lines += [
        "### Final critique",
        "",
        data["final_critique"] or "_(empty — approved)_",
        "",
        "### Final article (article_markdown)",
        "",
        data["article_markdown"],
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    # Edge case: empty topic must return HTTP 400.
    bad = requests.post(f"{API_URL}/get_article", json={"topic": "   "})
    assert bad.status_code == 400, f"expected 400 for empty topic, got {bad.status_code}"
    print("Edge case OK: empty topic -> HTTP 400")

    for case in CASES:
        evidence = run_case(case)
        path = OUT_DIR / f"{case['name']}.md"
        path.write_text(evidence, encoding="utf-8")
        print(f"  -> saved {path}")

    print("\nAll test evidence saved. Paste the files from tests_evidence/ into the README.")


if __name__ == "__main__":
    sys.exit(main())
