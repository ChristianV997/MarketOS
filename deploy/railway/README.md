# Railway FastAPI target

Railway is the recommended fast backend path: deploy the repository with the
profile startup command `uvicorn backend.api:app --host 0.0.0.0 --port $PORT`.
Configure `/health` and `/ready` as probes, set `MARKETOS_MVP_MODE=1`, and copy
only server-safe variables from `deploy/mvp/.env.mvp.example`. Start without
Supabase credentials to prove the JSONL/fixture path first. No worker, queue,
or background orchestrator should be enabled for the MVP Island.

The companion `railway.json` is a minimal template. Review the service root,
origin, artifact persistence, and operator-managed variables in Railway before
deploying; it does not create a project or provide credentials.
