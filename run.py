"""run.py — convenience launcher.

The canonical runtime spine is ``orchestrator.main`` (phase-driven tick
loop dispatching signal ingestion, execution, feedback, content generation,
scaling, metrics ingestion, and sleep consolidation).  This shim simply
delegates so ``python run.py`` and ``python -m orchestrator.main`` are the
same thing — one way to start the system.

For credential-free local API startup and Docker Compose packaging, see
``docs/LOCAL_RUNTIME_RUNBOOK.md``.
"""
import logging

from orchestrator.main import run

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
