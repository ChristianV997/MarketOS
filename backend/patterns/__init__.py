"""backend.patterns — shared framework utilities extracted from repeated code.

Each module here replaces a pattern that was copy-pasted across 3+ call
sites (worker error handling, dry-run branching, error taxonomy, result
caching). Extracting them keeps behavior consistent and makes it cheap to
add new workers/integrations without re-deriving the same boilerplate.
"""
