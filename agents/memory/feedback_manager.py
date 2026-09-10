"""
feedback_manager.py
-------------------
Location: agents/memory/feedback_manager.py

Plug-in / Plug-out Feedback Memory.

TO DISABLE: comment 2 lines in main.py + 1 line in plan_node
TO ENABLE : uncomment those lines

Handles:
  1. Save feedback  → thumbs up/down + comment
  2. Load hints     → inject past corrections into plan_node
  3. Get report     → analytics on good/bad answers
"""

import os
import json
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("feedback_manager")

# ══════════════════════════════════════════════════════════════
# CONFIG — change only here
# ══════════════════════════════════════════════════════════════

FEEDBACK_DIR  = os.path.join(os.path.dirname(__file__), "feedback")
FEEDBACK_FILE = os.path.join(FEEDBACK_DIR, "feedback.json")
MAX_HINTS     = 3      # max corrections injected into plan_node
MIN_RATING    = 0      # 0 = thumbs down
MAX_RATING    = 1      # 1 = thumbs up

# ══════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════

os.makedirs(FEEDBACK_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════
# PUBLIC 1 — save_feedback()
# Called by POST /feedback endpoint in main.py
# ══════════════════════════════════════════════════════════════

def save_feedback(
    question      : str,
    answer        : str,
    sql           : str  = "",
    domain        : str  = "",
    rating        : int  = 1,    # 1=thumbs up, 0=thumbs down
    comment       : str  = "",   # user's text comment
    session_id    : str  = "",
) -> Dict[str, Any]:
    """
    Saves user feedback to JSON file.

    Args:
        question   : original user question
        answer     : agent answer that was rated
        sql        : SQL that was generated
        domain     : crew / general
        rating     : 1=good, 0=bad
        comment    : user's text explaining what was wrong
        session_id : session this came from

    Returns:
        { "status": "saved", "feedback_id": str }
    """
    feedback_id = str(uuid.uuid4())[:8]

    entry = {
        "feedback_id" : feedback_id,
        "session_id"  : session_id,
        "question"    : question,
        "answer"      : answer,
        "sql"         : sql,
        "domain"      : domain,
        "rating"      : rating,        # 1=good, 0=bad
        "comment"     : comment,       # why it was wrong
        "verified"    : False,         # admin verified?
        "used_count"  : 0,             # how many times used as hint
        "timestamp"   : datetime.now().isoformat(),
    }

    # Load existing
    all_feedback = _load_all()

    # Append
    all_feedback.append(entry)

    # Save
    _save_all(all_feedback)

    rating_str = "👍" if rating == 1 else "👎"
    print(f"   📝 Feedback saved: {feedback_id} | {rating_str} | comment: '{comment[:50]}'")

    return {"status": "saved", "feedback_id": feedback_id}


# ══════════════════════════════════════════════════════════════
# PUBLIC 2 — load_hints()
# Called by plan_node BEFORE LLM generates SQL
# ══════════════════════════════════════════════════════════════

def load_hints(question: str, domain: str = "crew") -> List[Dict]:
    """
    Finds similar past bad answers with user corrections.
    Returns top N hints to inject into plan_node prompt.

    Matching strategy: keyword overlap (simple, no embeddings)

    Args:
        question: current user question
        domain  : filter by domain

    Returns:
        List of hint dicts:
        [{ question, comment, sql, answer }]
    """
    all_feedback = _load_all()

    # Filter: only bad answers (rating=0) with comments
    bad_feedback = [
        f for f in all_feedback
        if f.get("rating") == 0
        and f.get("comment", "").strip()
        and f.get("domain", "") == domain
    ]

    if not bad_feedback:
        return []

    # Score by keyword overlap
    q_words = set(question.lower().split())
    scored  = []

    for f in bad_feedback:
        f_words  = set(f["question"].lower().split())
        overlap  = len(q_words & f_words)
        if overlap >= 2:   # at least 2 words match
            scored.append((overlap, f))

    # Sort by overlap score
    scored.sort(key=lambda x: x[0], reverse=True)

    # Take top N
    hints = []
    for _, f in scored[:MAX_HINTS]:
        hints.append({
            "question": f["question"],
            "comment" : f["comment"],
            "sql"     : f.get("sql", ""),
        })
        # Increment used_count
        f["used_count"] = f.get("used_count", 0) + 1

    if hints:
        # Save updated used_count
        _save_all(all_feedback)
        print(f"   📝 Feedback hints loaded: {len(hints)} corrections injected")

    return hints


# ══════════════════════════════════════════════════════════════
# PUBLIC 3 — get_report()
# Called by GET /feedback/report endpoint
# ══════════════════════════════════════════════════════════════

def get_report() -> Dict[str, Any]:
    """
    Returns analytics summary of all feedback.

    Returns:
        {
            total, good, bad, bad_rate,
            top_issues, recent_bad
        }
    """
    all_feedback = _load_all()

    if not all_feedback:
        return {
            "total"      : 0,
            "good"       : 0,
            "bad"        : 0,
            "bad_rate"   : "0%",
            "top_issues" : [],
            "recent_bad" : [],
        }

    total = len(all_feedback)
    good  = sum(1 for f in all_feedback if f.get("rating") == 1)
    bad   = total - good

    # Top issues — most common bad comments
    comments  = [f["comment"] for f in all_feedback if f.get("rating") == 0 and f.get("comment")]
    top_issues = list(set(comments))[:5]

    # Recent bad answers
    recent_bad = [
        {
            "question" : f["question"],
            "comment"  : f["comment"],
            "timestamp": f["timestamp"],
        }
        for f in all_feedback
        if f.get("rating") == 0
    ][-10:]   # last 10

    return {
        "total"      : total,
        "good"       : good,
        "bad"        : bad,
        "bad_rate"   : f"{round(bad / total * 100, 1)}%",
        "top_issues" : top_issues,
        "recent_bad" : recent_bad,
    }


# ══════════════════════════════════════════════════════════════
# PUBLIC 4 — build_hint_prompt()
# Called by plan_node to format hints for LLM
# ══════════════════════════════════════════════════════════════

def build_hint_prompt(hints: List[Dict]) -> str:
    """
    Formats hints into a string to inject into plan_node prompt.

    Args:
        hints: list from load_hints()

    Returns:
        Formatted string for LLM prompt
    """
    if not hints:
        return ""

    text = "\n\n⚠️  PAST MISTAKES TO AVOID:\n"
    text += "These similar questions had wrong answers before.\n"
    text += "Read the feedback and avoid the same mistake:\n\n"

    for i, hint in enumerate(hints, 1):
        text += f"Example {i}:\n"
        text += f"  Question : {hint['question']}\n"
        text += f"  Was wrong: {hint['comment']}\n"
        if hint.get("sql"):
            text += f"  Bad SQL  : {hint['sql'][:150]}\n"
        text += "\n"

    text += "→ Make sure your SQL avoids these mistakes.\n"
    return text


# ══════════════════════════════════════════════════════════════
# PRIVATE HELPERS
# ══════════════════════════════════════════════════════════════

def _load_all() -> List[Dict]:
    """Loads all feedback from JSON file."""
    if not os.path.exists(FEEDBACK_FILE):
        return []
    try:
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"   ⚠️  Feedback load failed: {exc}")
        return []


def _save_all(data: List[Dict]) -> None:
    """Saves all feedback to JSON file."""
    try:
        with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"   ⚠️  Feedback save failed: {exc}")