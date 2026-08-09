"""run.py — convenience launcher.

The canonical runtime spine is ``orchestrator.main`` (phase-driven tick
loop dispatching signal ingestion, execution, feedback, content generation,
scaling, metrics ingestion, and sleep consolidation).  This shim simply
delegates so ``python run.py`` and ``python -m orchestrator.main`` are the
same thing — one way to start the system.
"""
import logging

from orchestrator.main import run

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
