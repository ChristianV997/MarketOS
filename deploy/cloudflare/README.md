# Cloudflare target

Use Cloudflare first for DNS, TLS, CDN, and WAF in front of Vercel/Railway or
Render. Workers, D1, R2, Queues, and AI Gateway are evaluation options—not part
of this profile. Do not move FastAPI business logic to Workers or store service
credentials in edge-visible variables without a dedicated design and test pass.
