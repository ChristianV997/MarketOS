# Creative Intelligence v1

Creative Intelligence turns local, persisted commercial and product intelligence into deterministic creative planning artifacts. It produces buyer psychology maps, angles, hooks, UGC brief drafts, storyboard outlines, a landing-page claim map, and a creative test matrix.

## Evidence and safety

Every output is a hypothesis or draft unless linked evidence supports a narrower descriptive statement. The layer does not call external APIs, publish ads, write to ad platforms, predict ROAS/conversion/profit, create testimonials, or claim scarcity. Claim safety blocks guarantees, financial-performance language, unsupported medical/legal/safety claims, fabricated reviews, and false urgency.

## Workflow

1. Import local/manual evidence and run Commercial Intelligence.
2. Run `POST /api/creative-intelligence/cycle` for an opportunity or product.
3. Review the buyer map, angles, hooks, claim map, and test matrix.
4. Collect the identified proof through manual/local imports.
5. Add only substantiated material to a separately approved future validation process.

The creative test matrix is a local review plan. It does not launch an ad or forecast performance.

## API

- `POST /api/creative-intelligence/cycle`
- `POST /api/creative-intelligence/buyer-psychology`
- `POST /api/creative-intelligence/angles/generate`
- `POST /api/creative-intelligence/hooks/generate`
- `POST /api/creative-intelligence/claims/validate`
- `GET /api/creative-intelligence/reports`, `/angles`, `/hooks`, `/ugc-briefs`, `/storyboards`, `/claim-maps`, `/test-matrices`

Artifacts are persisted in `state/creative_intelligence_registry.json`. Configured Obsidian notes remain local vault files under `MarketOS/03_CreativeIntelligence/`.

## Integrations

Creative reports are advisory inputs to validation deliverables, the knowledge graph, strategic planning, optimization, and the `creative_intelligence` workflow stage. They never override opportunity gates or authorize launch activity.
