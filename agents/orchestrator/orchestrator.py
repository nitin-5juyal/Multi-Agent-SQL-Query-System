"""
orchestrator.py
---------------
Orchestrator — The Brain.
"""

from dotenv import load_dotenv
load_dotenv()

import logging
from typing import Any, Dict

from agents.router import classify_intent, classify_domain
from agents.general_agent import handle_general

# ── Sub-Agent Registry ───────────────────
from agents.sub_agents.crew_agent import run_crew_agent

from agents.memory.memory_manager import (
    load_session,
    save_session,
    get_short_term,
    resolve_references
)

AGENT_REGISTRY: Dict[str, Any] = {
    "crew": run_crew_agent,
}

logger = logging.getLogger("orchestrator")


# ─────────────────────────────────────────
# INTERNAL: call sub-agent
# ─────────────────────────────────────────
def _call_sub_agent(domain: str, question: str) -> dict:
    print("\n" + "─" * 60)
    print(f"🔀 ORCHESTRATOR → calling sub-agent for domain: '{domain}'")
    print("─" * 60)

    agent_fn = AGENT_REGISTRY.get(domain)

    # ❌ No agent found
    if not agent_fn:
        print(f"   ⚠️  No agent registered for domain '{domain}'")
        return {
            "status": "fail",
            "answer": f"No agent available for '{domain}'.",
            "sql": "",
            "columns": [],
            "rows": [],
            "domain": domain,
        }

    try:
        print(f"   🚀 Calling {agent_fn.__module__}.{agent_fn.__name__}...")
        result = agent_fn(question=question, domain=domain)

        # ✅ SUCCESS (even if 0 rows)
        if result:
            print(f"   ✅ Sub-agent success — {len(result.get('rows', []))} rows")
            return result

    except Exception as exc:
        print(f"   ❌ Sub-agent exception: {exc}")

    # ❌ ONLY REAL FAILURE → fallback
    return {
        "status": "fail",
        "answer": "Error while processing request.",
        "sql": "",
        "columns": [],
        "rows": [],
        "domain": domain,
    }

# ─────────────────────────────────────────
# MAIN ENTRY
# ─────────────────────────────────────────
def run_orchestrator(question: str, session_id: str = "") -> dict:
    print("\n" + "█" * 60)
    print("🧠 ORCHESTRATOR START")
    print("█" * 60)
    print(f"   Question: {question}")

    # 🧠 Load session ONCE
    session  = load_session(session_id)

    # 🧠 Resolve references — pass session directly
    question = resolve_references(question, session)
    if not question or not question.strip():
        return {
            "answer": "Please ask a question.",
            "sql": "",
            "columns": [],
            "rows": [],
            "intent": "",
            "domain": "",
        }

    # STEP 1 — Intent
    intent = classify_intent(question)
    print(f"\n   ✅ Intent  : {intent}")

    # STEP 2 — GENERAL
    if intent == "GENERAL":
        print("   ↪️  Routing to general agent")
        answer = handle_general(question)
        return {
            "answer": answer,
            "sql": "",
            "columns": [],
            "rows": [],
            "intent": intent,
            "domain": "general",
        }

    # STEP 3 — Domain
    domain = classify_domain(question)
    print(f"   ✅ Domain  : {domain}")

    # 🧠 Reset context if domain changed — prevents context bleeding
    from agents.memory.memory_manager import reset_context_if_needed
    reset_context_if_needed(session, domain)

    # STEP 4 — Call sub-agent
    # 🧠 Get short-term — pass session directly
    short_term = get_short_term(session)

    # Call agent with memory
    result = run_crew_agent(
        question=question,
        domain=domain,
        short_term=short_term
    )

    # ✅ SUCCESS — rows found OR genuinely no data (valid query)
    if result and result.get("status") == "success":
        print("✅ Crew agent success (no fallback)")
        # 🧠 Save session
        save_session(
            session_id=session_id,
            question=question,
            answer=result.get("answer", ""),
            sql=result.get("sql", ""),
            domain=domain,
            columns=result.get("columns", []),
            row_count=len(result.get("rows", []))
        )
        return {
            "answer" : result.get("answer", ""),
            "sql"    : result.get("sql", ""),
            "columns": result.get("columns", []),
            "rows"   : result.get("rows", []),
            "intent" : intent,
            "domain" : domain,
        }

    # ❌ REAL FAILURE → fallback
    fail_reason = result.get("fail_reason", "unknown") if result else "no_result"
    print(f"❌ Crew agent failed → reason: {fail_reason} → triggering fallback")

    # ── Build full context for fallback ──────────────────────
    # Fallback knows what crew agent tried → avoids same mistakes
    fallback_context = {
        "original_question" : question,
        "fail_reason"       : fail_reason,
        "failed_sql"        : result.get("sql", "") if result else "",
        "failed_tables"     : result.get("columns", []) if result else [],
        "error_detail"      : result.get("answer", "") if result else "",
        "domain"            : domain,
    }
    print(f"   📦 Fallback context: reason={fail_reason} | sql={fallback_context['failed_sql'][:60]}")

    from agents.fallback_agent.agent import run_agent
    fallback = run_agent(question, context=fallback_context)  # ← context passed

    return {
        "answer" : fallback.get("answer", ""),
        "sql"    : fallback.get("sql", ""),
        "columns": fallback.get("columns", []),
        "rows"   : fallback.get("rows", []),
        "intent" : intent,
        "domain" : domain,
    }