import type { OfferingDraft, ProfileDraft, SocialAccountDraft } from "../contracts/clientProfileDraft.ts";

/**
 * Fictional demo data. Nothing here describes a real company, person, account
 * or product. It exists so the demo can show a completed review.
 */
export function buildSampleDraft(keyFor: (prefix: string, index: number) => string): ProfileDraft {
  const offerings: OfferingDraft[] = [
    {
      key: keyFor("offering", 0),
      name: "Demo Pour-Over Kettle",
      description: "Fictional sample product used only in the demo.",
      delivery: "",
      availability: "in_stock",
      sku: "DEMO-KETTLE-01",
      quantity: "40",
    },
    {
      key: keyFor("offering", 1),
      name: "Demo Grinder",
      description: "",
      delivery: "",
      availability: "made_to_order",
      sku: "",
      quantity: "",
    },
  ];
  const socialAccounts: SocialAccountDraft[] = [
    {
      key: keyFor("social", 0),
      platform: "instagram",
      handle: "example_demo_account",
      url: "",
      notes: "Fictional sample handle. Not connected.",
    },
  ];
  return {
    companyName: "Example Demo Coffee Co. (sample)",
    businessType: "product",
    categories: ["Coffee equipment"],
    segments: ["Home baristas", "Gift shoppers"],
    targetMarkets: ["United States", "Canada"],
    offerings,
    socialAccounts,
  };
}
