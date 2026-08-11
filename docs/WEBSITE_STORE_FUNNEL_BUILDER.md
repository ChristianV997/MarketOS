# Platform-Agnostic Website / Store / Funnel Draft Builder v1

The Site Draft Builder is the implementation-planning upsell after Launch Draft Pack. It turns existing launch copy and evidence into a portable blueprint for ecommerce and non-ecommerce clients:

- route manifest, sitemap, navigation, and page goals;
- composable sections and blocks with evidence/risk notes;
- reusable section schemas and CMS content models;
- lead capture, SEO, analytics, and conversion-test plans;
- static, Shopify, Medusa, WooCommerce, Webflow, Wix, Squarespace, and Carrd-shaped draft payloads;
- deployment readiness, approval checklist, and risk review.

It is not a storefront generator. It does not emit Liquid, React storefront code, theme uploads, domain changes, hosting changes, API calls, analytics installation, checkout activation, publishing, or spend.

## Run it

Offline fixture mode:

```powershell
python scripts/generate_site_draft_pack.py --json
python scripts/generate_site_draft_pack.py --markdown
```

With a client context and site type:

```powershell
python scripts/generate_site_draft_pack.py `
  --client-context tests/fixtures/site_draft_builder/service_business_context.json `
  --site-type service_business_website `
  --markdown
```

Use an existing Launch Draft Pack and synthesis report:

```powershell
python scripts/generate_site_draft_pack.py `
  --launch-draft-pack artifacts/launch_draft_pack/latest/launch_draft_pack.json `
  --opportunity-synthesis-report artifacts/opportunity_synthesis/latest/opportunity_synthesis_report.json `
  --client-context tests/fixtures/site_draft_builder/ecommerce_context.json `
  --site-type ecommerce_store `
  --output artifacts/site_draft_pack/latest `
  --markdown
```

## Platform mapping

The payloads intentionally describe concepts instead of using platform APIs:

- Shopify: theme templates, sections, settings, product/collection templates, and draft metafields.
- Medusa: storefront routes, product/collection pages, cart and checkout handoff placeholders, and sales-channel placeholders.
- WooCommerce: pages, products, categories, attributes, and SEO fields.
- Webflow: CMS collections, fields, items, and collection pages.
- Wix/Squarespace: business data, products/services, content pages, and hidden/draft visibility.
- Carrd: one-page sections, forms, embeds, custom-code placeholders, and tracking placeholders.

This maps the implementation conversation without locking a client into a platform or adding a dependency.

## Evidence and approval

Unknown contact details, addresses, legal policies, specifications, inventory, claims, testimonials, reviews, certifications, and search performance remain `TBD`. SEO output does not invent volume or rank. Analytics output describes events and consent decisions; it does not install pixels. Conversion thresholds are planning inputs from the existing synthesis and do not authorize traffic or spend.

The deployment checklist, approval checklist, and risk review are part of the deliverable. Publishing remains false until the client approves copy, claims, supplier proof, pricing, shipping, policies, assets, SEO, analytics/privacy, and the draft payload.
