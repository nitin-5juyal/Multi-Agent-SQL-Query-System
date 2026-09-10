"""
memory_manager.py
-----------------
Location: agents/memory/memory_manager.py

Plug-in / Plug-out Session Memory.

TO DISABLE: comment 4 lines in orchestrator.py
TO ENABLE : uncomment those 4 lines

Handles:
  1. Session Memory  → full conversation per session (JSON file)
  2. Short-Term      → last N messages slice for LLM context
  3. Context Resolve → resolves explicit + implicit references
"""

import os
import re
import json
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("memory_manager")

# ══════════════════════════════════════════════════════════════
# CONFIG — change only here
# ══════════════════════════════════════════════════════════════

SESSIONS_DIR         = os.path.join(os.path.dirname(__file__), "sessions")
MAX_SESSION_MSGS     = 50
SHORT_TERM_SLICE     = 6
MAX_SESSION_AGE_DAYS = 7

# ── NEW — City → Base code map ────────────────────────────────
CITY_MAP = {
    "mumbai"   : "BOM",
    "delhi"    : "DEL",
    "bangalore": "BLR",
    "bengaluru": "BLR",
    "hyderabad": "HYD",
    "kolkata"  : "CCU",
    "kochi"    : "COK",
    "cochin"   : "COK",
    "kozhikode": "CCJ",
    "vadodara" : "BDQ",
    "kannur"   : "CNN",
    "mangalore": "IXE",
}

BASE_CODES = ["DEL", "BOM", "BLR", "HYD", "CCU", "COK", "CCJ", "BDQ", "CNN", "IXE"]

# Reference words — explicit follow-up signals
REFERENCE_WORDS = [
    "them", "those", "these", "they",
    "same", "same base", "same rank", "same fleet",
    "that crew", "those crew", "of them", "among them",
    "their", "its",
]

# ══════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════

os.makedirs(SESSIONS_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════
# PUBLIC 1 — generate_session_id()
# ══════════════════════════════════════════════════════════════

def generate_session_id() -> str:
    session_id = str(uuid.uuid4())[:8]
    print(f"   🧠 New session ID: {session_id}")
    return session_id


# ══════════════════════════════════════════════════════════════
# PUBLIC 2 — load_session()
# ══════════════════════════════════════════════════════════════

def load_session(session_id: str) -> Dict[str, Any]:
    path = _session_path(session_id)

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                session = json.load(f)
            print(f"   🧠 Session loaded: {session_id} ({len(session.get('messages', []))} messages)")
            return session
        except Exception as exc:
            print(f"   ⚠️  Session load failed: {exc} — starting fresh")

    return _empty_session(session_id)


# ══════════════════════════════════════════════════════════════
# PUBLIC 3 — save_session()
# ══════════════════════════════════════════════════════════════

def save_session(
    session_id: str,
    question  : str,
    answer    : str,
    sql       : str  = "",
    domain    : str  = "",
    columns   : List = None,
    row_count : int  = 0,
) -> None:
    session = load_session(session_id)

    message = {
        "question" : question,
        "answer"   : answer,
        "sql"      : sql,
        "domain"   : domain,
        "columns"  : columns or [],
        "row_count": row_count,
        "timestamp": datetime.now().isoformat(),
    }

    session["messages"].append(message)

    if len(session["messages"]) > MAX_SESSION_MSGS:
        session["messages"] = session["messages"][-MAX_SESSION_MSGS:]
        print(f"   🧹 Session trimmed to {MAX_SESSION_MSGS} messages")

    # Update last_context + last_domain
    session["last_context"] = _extract_context(
        question, sql, session.get("last_context", {})
    )
    session["last_domain"]  = domain or session.get("last_domain", "")
    session["last_updated"] = datetime.now().isoformat()

    try:
        path = _session_path(session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, indent=2, ensure_ascii=False)
        print(f"   🧠 Session saved: {session_id}")
    except Exception as exc:
        print(f"   ⚠️  Session save failed: {exc}")


# ══════════════════════════════════════════════════════════════
# PUBLIC 4 — get_short_term()
# ══════════════════════════════════════════════════════════════

def get_short_term(session: dict) -> List[Dict]:
    messages = session.get("messages", [])
    recent   = messages[-SHORT_TERM_SLICE:]

    formatted = []
    for msg in recent:
        formatted.append({
            "role"   : "user",
            "content": msg["question"],
        })
        if msg.get("answer"):
            assistant_content = msg["answer"]
            if msg.get("sql"):
                assistant_content += f"\n[SQL used: {msg['sql'][:200]}]"
            formatted.append({
                "role"   : "assistant",
                "content": assistant_content,
            })

    print(f"   🧠 Short-term: {len(formatted)} messages injected into LLM context")
    return formatted


# ══════════════════════════════════════════════════════════════
# PUBLIC 5 — resolve_references()   ← UPGRADED
# Handles BOTH explicit + implicit follow-ups
# ══════════════════════════════════════════════════════════════

def resolve_references(question: str, session: dict) -> str:
    """
    Resolves both explicit and implicit follow-up references.

    Explicit: "their", "them", "those", "same"
    Implicit: no new filter mentioned but context exists

    Args:
        question : raw user question
        session  : loaded session dict

    Returns:
        Enriched question string with [context: ...] appended
    """
    last_context = session.get("last_context", {})

    if not last_context:
        return question

    q_lower = question.lower()

   # Safety check — domain must match before applying context
    current_domain = session.get("last_domain", "")
    if current_domain and current_domain not in ["crew", ""]:
        print("   🧠 Context skipped — domain mismatch")
        return question

    # Check explicit reference words
    has_explicit = any(word in q_lower for word in REFERENCE_WORDS)

    # Check implicit follow-up
    has_implicit = is_implicit_followup(question, session)

    # Already has context injected — skip to avoid duplicates
    if "[context:" in question:
        return question

    if not has_explicit and not has_implicit:
        return question

    # Build context hint — capped at 3 fields max (base > rank > fleet)
    hints = []
    if last_context.get("last_base"):
        hints.append(f"base={last_context['last_base']}")
    if last_context.get("last_rank") and len(hints) < 3:
        hints.append(f"rank={last_context['last_rank']}")
    if last_context.get("last_fleet") and len(hints) < 3:
        hints.append(f"fleet={last_context['last_fleet']}")
    # domain dropped — redundant, saves tokens


    if hints:
        enriched = f"{question} [context: {', '.join(hints)}]"
        reason   = "explicit" if has_explicit else "implicit"
        print(f"   🧠 Reference resolved ({reason}): '{question}' → '{enriched}'")
        return enriched

    return question


# ══════════════════════════════════════════════════════════════
# PUBLIC 6 — is_implicit_followup()   ← NEW
# ══════════════════════════════════════════════════════════════

def is_implicit_followup(question: str, session: dict) -> bool:
    """
    Returns True if:
    - session has last_context (previous query existed)
    - no new base/city/rank mentioned in current question
    - question is short (likely a follow-up)

    Args:
        question : current user question
        session  : loaded session dict

    Returns:
        bool
    """
    last_context = session.get("last_context", {})

    # No previous context → not a follow-up
    if not last_context:
        return False

    q_lower = question.lower()
    words   = q_lower.split()

    # If new city mentioned → new query, not follow-up
    for city in CITY_MAP:
        if city in q_lower:
            return False

    # If new base code mentioned → new query
    for code in BASE_CODES:
        if re.search(r'\b' + code + r'\b', question, re.IGNORECASE):
            return False

    # Rank words alone do NOT break context
    # Only a completely new base/city resets base context
    # So remove rank check here — rank enriches, not resets

    # If question is very long → likely new query
    if len(words) > 12:
        return False

    # Conceptual/general questions → never follow-up
    conceptual_words = [
        "what is", "what are", "how does", "how do",
        "explain", "define", "tell me about", "why",
        "difference", "describe", "meaning"
    ]
    if any(w in q_lower for w in conceptual_words):
        return False

    # Short question + has previous context → implicit follow-up
    return True


# ══════════════════════════════════════════════════════════════
# PUBLIC 7 — reset_context_if_needed()   ← NEW
# ══════════════════════════════════════════════════════════════

def reset_context_if_needed(session: dict, new_domain: str) -> None:
    """
    Clears last_context if domain changes.
    Prevents context bleeding between domains.

    Args:
        session    : loaded session dict (modified in place)
        new_domain : domain of current query
    """
    last_domain = session.get("last_domain", "")

    if last_domain and new_domain and last_domain != new_domain:
        print(f"   🧠 Domain changed: '{last_domain}' → '{new_domain}' — resetting context")
        session["last_context"] = {}
        session["last_domain"]  = new_domain


# ══════════════════════════════════════════════════════════════
# PUBLIC 8 — get_context_prompt()   ← NEW
# ══════════════════════════════════════════════════════════════

def get_context_prompt(session: dict) -> str:
    """
    Returns formatted context string for injection into plan_node prompt.

    Args:
        session : loaded session dict

    Returns:
        Formatted string or empty string if no context
    """
    last_context = session.get("last_context", {})

    if not last_context:
        return ""

    lines = ["Previous Query Context (reuse these filters if relevant):"]

    if last_context.get("last_base"):
        lines.append(f"  Base  = {last_context['last_base']}")
    if last_context.get("last_rank"):
        lines.append(f"  Rank  = {last_context['last_rank']}")
    if last_context.get("last_fleet"):
        lines.append(f"  Fleet = {last_context['last_fleet']}")
    if last_context.get("last_domain"):
        lines.append(f"  Domain= {last_context['last_domain']}")

    if len(lines) == 1:
        return ""

    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════
# PRIVATE HELPERS
# ══════════════════════════════════════════════════════════════

def _session_path(session_id: str) -> str:
    return os.path.join(SESSIONS_DIR, f"{session_id}.json")


def cleanup_old_sessions() -> None:
    import time
    now    = time.time()
    cutoff = now - (MAX_SESSION_AGE_DAYS * 86400)
    deleted = 0

    try:
        for filename in os.listdir(SESSIONS_DIR):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(SESSIONS_DIR, filename)
            if os.path.getmtime(filepath) < cutoff:
                os.remove(filepath)
                deleted += 1
                print(f"   🗑️  Deleted old session: {filename}")
        print(f"   🧹 Session cleanup done — {deleted} files deleted")
    except Exception as exc:
        print(f"   ⚠️  Session cleanup failed: {exc}")


def _empty_session(session_id: str) -> Dict[str, Any]:
    return {
        "session_id"  : session_id,
        "messages"    : [],
        "last_context": {},
        "last_domain" : "",
        "created_at"  : datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
    }


def _extract_context(question: str, sql: str, existing: Dict) -> Dict:
    """
    Extracts filter context from question and SQL.
    Handles city names → base codes + direct base codes.
    Updates existing context with new values only.
    """
    context = dict(existing)
    q_lower = question.lower()
    words   = q_lower.split()

    # Ensure structured filters dict exists
    if "filters" not in context:
        context["filters"] = {}

    # ── Extract base from city name ───────────────────────────
    for city, code in CITY_MAP.items():
        if city in q_lower:
            context["last_base"]         = code
            context["filters"]["Base"]   = code   # structured ✅
            print(f"   🧠 Context: city '{city}' → base '{code}'")
            break

    # ── Extract base from direct base code ───────────────────
    base_match = re.search(
        r'\b(' + '|'.join(BASE_CODES) + r')\b',
        question, re.IGNORECASE
    )
    if base_match:
        code                             = base_match.group(1).upper()
        context["last_base"]             = code
        context["filters"]["Base"]       = code   # structured ✅
        print(f"   🧠 Context: base code '{code}'")

    # ── Extract rank — ONLY if explicitly in current question ─
    # Never carry rank from old sessions unless user said it now
    rank_found = False
    if any(w in q_lower for w in ["captain", " cp ", "commander"]):
        context["last_rank"]           = "CP"
        context["filters"]["RankCode"] = "CP"
        rank_found = True
    elif any(w in q_lower for w in ["first officer", " fo ", "copilot"]):
        context["last_rank"]           = "FO"
        context["filters"]["RankCode"] = "FO"
        rank_found = True
    elif any(w in q_lower for w in ["cabin crew", "flight attendant", " fa "]):
        context["last_rank"]           = "CC"
        context["filters"]["RankCode"] = "CC"
        rank_found = True
    elif "scc" in words:
        context["last_rank"]           = "SCC"
        context["filters"]["RankCode"] = "SCC"
        rank_found = True
    elif "trcc" in words:
        context["last_rank"]           = "TRCC"
        context["filters"]["RankCode"] = "TRCC"
        rank_found = True

    # If no rank in current question → clear stale rank from context
    if not rank_found:
        context.pop("last_rank", None)
        context.get("filters", {}).pop("RankCode", None)

    # ── Extract fleet — ONLY if explicitly in current question ─
    fleet_match = re.search(
        r'\b(A320|A321|B737|B777|A319|32F|32N)\b',
        question, re.IGNORECASE
    )
    if fleet_match:
        context["last_fleet"] = fleet_match.group(1).upper()
    else:
        # Clear stale fleet — user didn't mention it
        context.pop("last_fleet", None)
        context.get("filters", {}).pop("Fleet", None)

    return context