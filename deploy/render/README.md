# Render FastAPI target

Render is the equivalent low-complexity FastAPI option. Use a Web Service,
build from `requirements.txt`, run the profile startup command, and configure
`/health` plus `/ready`. Apply the same no-worker, no-live-commerce, server-only
secret rules as Railway. Use this instead of Railway when its regional, pricing,
or team-operation model is a better fit; do not run both for the initial MVP.

`render.yaml` is an editable starting point with safe public-run and Supabase
write defaults. Review `ALLOWED_ORIGINS` and persistent artifact storage in the
Render console before deploying.
