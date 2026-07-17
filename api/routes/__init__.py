"""api.routes — focused FastAPI route modules split out of backend/api.py.

backend/api.py was a single 1,368-line file mixing lifecycle management,
shared mutable state, and 45+ route handlers. Each module here owns one
group of related endpoints; shared state (_state, _lock, _bg_running, ...)
still lives in backend/api.py and is referenced via ``import backend.api
as _core`` + qualified access (``_core._state``), never a destructured
``from backend.api import _state`` — several handlers reassign ``_state``
and ``_bg_running`` via ``global``, and only qualified module-attribute
access sees that reassignment; a bound name from a destructured import
would silently keep pointing at the object that existed at import time.
"""
