/**
 * Higgsfield public skills inspected as a future creative-asset contract only.
 * Source: https://github.com/higgsfield-ai/skills (product-photoshoot,
 * marketplace-cards, higgsfield-brandkit, higgsfield-video-explainer).
 * No SDK, API key, MCP, upload, generation, publication, or deploy.
 */

export const HIGGSFIELD_CONTRACT_SOURCE = "https://github.com/higgsfield-ai/skills";

export const HIGGSFIELD_DRAFT_SKILLS = [
  {
    skill_id: "product-photoshoot" as const,
    contract_name: "higgsfield-product-photoshoot",
    status: "unavailable" as const,
    generation_enabled: false as const,
    publication_enabled: false as const,
    note: "Future draft metadata only. Modes such as product_shot remain unexecuted.",
  },
  {
    skill_id: "marketplace-cards" as const,
    contract_name: "higgsfield-marketplace-cards",
    status: "unavailable" as const,
    generation_enabled: false as const,
    publication_enabled: false as const,
    note: "Future draft metadata only. Marketplace card scopes remain unexecuted.",
  },
  {
    skill_id: "brandkit" as const,
    contract_name: "higgsfield-brandkit",
    status: "unavailable" as const,
    generation_enabled: false as const,
    publication_enabled: false as const,
    note: "Future draft metadata only. Brandkit generation and uploads are disabled.",
  },
  {
    skill_id: "video-explainer" as const,
    contract_name: "higgsfield-video-explainer",
    status: "unavailable" as const,
    generation_enabled: false as const,
    publication_enabled: false as const,
    note: "Future draft metadata only. Explainer video assembly is disabled.",
  },
] as const;
