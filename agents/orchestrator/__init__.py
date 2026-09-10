"""
orchestrator/__init__.py
-------------------------
Public interface for orchestrator.
main.py imports ONLY this.
"""

from .orchestrator import run_orchestrator

__all__ = ["run_orchestrator"]