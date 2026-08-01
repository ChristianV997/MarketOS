# Obsidian Bridge Status

Status: local filesystem capture enabled; REST/MCP bridge remains deferred. Updated: 2026-07-31.

Obsidian is installed and its vault is configured at `C:\Users\HP\Documents\Obsidian Vault`. No local REST API plugin is installed or verified. The safe one-way filesystem bridge `scripts/ai/push_handoff_to_obsidian.py` is enabled instead.

The approved workflow captures only generated Markdown handoffs into `AI Engineering/Session Handoffs/`. It supports dry-run mode, uses the configured vault path, and never copies source files or secrets. The repository handoff remains the source of truth; Obsidian is a convenience mirror.
