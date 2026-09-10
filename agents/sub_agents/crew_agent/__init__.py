"""
orchestrator/__init__.py
-------------------------
Public interface for orchestrator.
main.py imports ONLY this.
"""

from .crew_agent import run_crew_agent

__all__ = ["run_crew_agent"]