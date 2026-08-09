# Vercel frontend target

Deploy `frontend/` as the Vite project. Set `VITE_API_BASE_URL` to the deployed
FastAPI base URL and keep secrets out of `VITE_*` variables. `VITE_POSTHOG_KEY`
is optional; the existing client is a no-op without it. Use preview deployments
for UI/API integration checks. Vercel hosts the interface only; it does not
receive a Supabase service-role key or gain authority to execute commerce work.
