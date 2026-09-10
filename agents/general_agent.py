"""
general_agent.py
----------------
Handles non-SQL questions: greetings, casual talk, explanations, help.
"""

import os
import logging
from groq import Groq

logger      = logging.getLogger("general_agent")
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
LLM_MODEL   = "llama-3.3-70b-versatile"


def handle_general(question: str) -> str:
    print("\n" + "═"*60)
    print("💬 GENERAL AGENT — Non-SQL question")
    print("═"*60)
    print(f"   Question : {question}")
    print("   Calling LLM for conversational response...")

    system_prompt = (
        "You are a helpful assistant for an airline crew management system.\n"
        "Answer the user's question in a friendly, concise way.\n"
        "If the user asks about data or records, tell them to ask a specific data question.\n"
        "Keep your response under 3 sentences."
    )

    try:
        resp = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": question},
            ],
            temperature=0.3,
            max_tokens=150,
        )
        answer = resp.choices[0].message.content.strip()
        print(f"   ✅ General answer: {answer}")
        return answer

    except Exception as exc:
        print(f"   ❌ General agent failed: {exc}")
        return "I'm here to help with crew management data. Please ask a specific question about crew, rosters, leaves, or documents."


# Alias for backward compatibility with older imports
run_general_agent = handle_general