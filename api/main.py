# """
# main.py
# -------
# FastAPI entry point.

# FINAL FLOW:
# main.py → orchestrator → crew agent → fallback → return

# RULE:
# - main.py does NOT do any logic
# - ONLY forwards request to orchestrator
# """

# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel
# import traceback
# import logging

# from agents.guardrails.input_guard import guard_input
# from agents.memory.memory_manager import generate_session_id
# # ✅ ONLY THIS IMPORT (brain of system)
# from agents.orchestrator.orchestrator import run_orchestrator

# logger = logging.getLogger("main")

# app = FastAPI(title="AI Multi-Agent System")


# # ================= REQUEST MODEL =================
# class QuestionRequest(BaseModel):
#     question: str
#     session_id: str = "user_001"


# # ================= HEALTH CHECK =================
# @app.get("/")
# def root():
#     return {"status": "✅ AI Agent System Running"}


# # ================= MAIN ENDPOINT =================
# @app.post("/ask")
# def ask(req: QuestionRequest):

#     if not req.question.strip():
#         raise HTTPException(status_code=400, detail="Question cannot be empty")

#     # 🔴 INPUT GUARD (MUST STOP EXECUTION)
#     check = guard_input(req.question)

#     if check.get("blocked"):
#         print("🚫 BLOCKED — stopping execution")
#         return {
#             "status": "success",   # 👈 important for frontend
#             "answer": check.get("message", "Request blocked"),
#             "sql": "",
#             "columns": [],
#             "rows": []
#         }

#     # 🛑 HARD STOP SAFETY (DOUBLE PROTECTION)
#     if check.get("blocked"):
#         return

#     print("➡️ SAFE — calling orchestrator")

#     try:
#         session_id = req.__dict__.get("session_id") or "user_001"

#         result = run_orchestrator(req.question, session_id=session_id)

#         return {
#             "question": req.question,
#             "intent"  : result.get("intent", ""),
#             "domain"  : result.get("domain", ""),
#             "answer"  : result.get("answer", ""),
#             "sql"     : result.get("sql", ""),
#             "columns" : result.get("columns", []),
#             "rows"    : result.get("rows", [])
#         }

#     except Exception as e:
#         traceback.print_exc()
#         raise HTTPException(status_code=500, detail=str(e))


"""
main.py
-------
FastAPI entry point.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import traceback
import logging

from agents.guardrails.input_guard import guard_input
from agents.orchestrator.orchestrator import run_orchestrator
from agents.memory.feedback_manager import save_feedback

app = FastAPI(title="AI Multi-Agent System")
logger = logging.getLogger("main")
# Cleanup old sessions on startup
from agents.memory.memory_manager import cleanup_old_sessions
cleanup_old_sessions()


# ================= REQUEST MODEL =================
class QuestionRequest(BaseModel):
    question: str
    session_id: str = "user_001"


# ================= HEALTH CHECK =================
@app.get("/")
def root():
    return {"status": "running"}


# ================= MAIN ENDPOINT =================
@app.post("/ask")
def ask(req: QuestionRequest):

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    # 🔴 INPUT GUARD
    check = guard_input(req.question)

    if check.get("blocked"):
        return {
            "status": "error",
            "answer": check.get("reason", "Request blocked"),
            "sql": "",
            "columns": [],
            "rows": []
        }

    try:
        result = run_orchestrator(
            req.question,
            session_id=req.session_id
        )

        return {
            "question": req.question,
            "intent": result.get("intent", ""),
            "domain": result.get("domain", ""),
            "answer": result.get("answer", ""),
            "sql": result.get("sql", ""),
            "columns": result.get("columns", []),
            "rows": result.get("rows", [])
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ================= FEEDBACK ENDPOINT =================
@app.post("/feedback")
def feedback(req: dict):

    try:
        return save_feedback(
            question=req.get("question", ""),
            answer=req.get("answer", ""),
            sql=req.get("sql", ""),
            domain=req.get("domain", ""),
            rating=req.get("rating", 1),
            comment=req.get("comment", ""),
            session_id=req.get("session_id", "user_001")
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))