import {
  BUSINESS_TYPE_META,
  LIMITS,
  STEP_IDS,
  STEP_META,
  type BusinessType,
  type OfferingDraft,
  type ProfileDraft,
  type ProfileErrorCode,
  type SocialAccountDraft,
  type StepId,
} from "../contracts/clientProfileDraft.ts";
import { buildSampleDraft } from "../fixtures/sampleProfile.ts";
import { buildPayload, payloadKey } from "./toPayload.ts";
import { validateProfile, type FieldError, type ProfileValidation } from "./validateProfile.ts";

export type TagField = "categories" | "segments" | "targetMarkets";

export type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved" }
  | { status: "error"; code: ProfileErrorCode };

/** Asks the view to move focus after the next render. `nonce` makes repeat requests distinct. */
export interface FocusRequest {
  target: "heading" | "summary" | "field";
  path: string | null;
  nonce: number;
}

export interface WizardState {
  draft: ProfileDraft;
  step: StepId;
  /** Steps where "Next" or "Confirm" was pressed with problems: show every error there. */
  attempted: StepId[];
  /** Field paths the person has left; their errors show even before "Next". */
  touched: string[];
  save: SaveState;
  /** payloadKey of the last successful save; "saved" only holds while the form still matches it. */
  savedKey: string | null;
  /** payloadKey the person confirmed in demo mode (nothing is persisted). */
  demoReviewedKey: string | null;
  /** Text typed into a tag box but not added yet. Kept here so moving on can flag it instead of dropping it. */
  pending: Record<TagField, string>;
  focus: FocusRequest | null;
  /** One sentence for the polite live region. */
  announcement: string;
  keyCounter: number;
}

export const EMPTY_DRAFT: ProfileDraft = {
  companyName: "",
  businessType: null,
  categories: [],
  segments: [],
  targetMarkets: [],
  offerings: [],
  socialAccounts: [],
};

export function initialWizardState(overrides: Partial<WizardState> = {}): WizardState {
  return {
    draft: EMPTY_DRAFT,
    step: "company",
    attempted: [],
    touched: [],
    save: { status: "idle" },
    savedKey: null,
    demoReviewedKey: null,
    pending: { categories: "", segments: "", targetMarkets: "" },
    focus: null,
    announcement: "",
    keyCounter: 0,
    ...overrides,
  };
}

export type WizardAction =
  | { type: "setCompanyName"; value: string }
  | { type: "setBusinessType"; value: BusinessType }
  | { type: "addTags"; field: TagField; tags: string[] }
  | { type: "setPending"; field: TagField; value: string }
  | { type: "removeTag"; field: TagField; index: number }
  | { type: "addOffering" }
  | { type: "updateOffering"; key: string; patch: Partial<Omit<OfferingDraft, "key">> }
  | { type: "removeOffering"; key: string }
  | { type: "addSocial" }
  | { type: "updateSocial"; key: string; patch: Partial<Omit<SocialAccountDraft, "key">> }
  | { type: "removeSocial"; key: string }
  | { type: "blur"; path: string }
  | { type: "next" }
  | { type: "back" }
  | { type: "goto"; step: StepId; path?: string | null }
  | { type: "confirmAttempt" }
  | { type: "loadSample" }
  | { type: "clear" }
  | { type: "saveStarted" }
  | { type: "saveSucceeded"; key: string }
  | { type: "saveFailed"; code: Extract<SaveState, { status: "error" }>["code"] }
  | { type: "demoReviewed"; key: string };

const TAG_LABEL: Record<TagField, { singular: string; plural: string; max: number }> = {
  categories: { singular: "category", plural: "categories", max: LIMITS.maxCategories },
  segments: { singular: "segment", plural: "segments", max: LIMITS.maxSegments },
  targetMarkets: { singular: "market", plural: "markets", max: LIMITS.maxTargetMarkets },
};

export function tagFieldRules(field: TagField) {
  return TAG_LABEL[field];
}

/** Text left in a tag box is a problem to resolve, never silently discarded. Never echoes the text. */
export function pendingErrors(pending: WizardState["pending"]): FieldError[] {
  return (Object.keys(TAG_LABEL) as TagField[])
    .filter((field) => pending[field].trim() !== "")
    .map((field) => ({
      path: field,
      step: "audience" as const,
      code: "invalid" as const,
      message: `There is text in the ${TAG_LABEL[field].singular} box that has not been added. Choose Add ${TAG_LABEL[field].singular}, or clear the box.`,
    }));
}

/** Whole-wizard validation: the draft plus any typed-but-not-added tag text. */
export function wizardValidation(state: Pick<WizardState, "draft" | "pending">): ProfileValidation {
  const base = validateProfile(state.draft);
  const extra = pendingErrors(state.pending);
  if (extra.length === 0) return base;
  const byStep = { ...base.byStep, audience: [...extra, ...base.byStep.audience] };
  return { errors: [...extra, ...base.errors], byStep, complete: false };
}

function stepNumber(step: StepId): number {
  return STEP_IDS.indexOf(step) + 1;
}

function stepAnnouncement(step: StepId): string {
  return `Step ${stepNumber(step)} of ${STEP_IDS.length}: ${STEP_META[step].title}.`;
}

function withFocus(state: WizardState, target: FocusRequest["target"], path: string | null = null): FocusRequest {
  return { target, path, nonce: (state.focus?.nonce ?? 0) + 1 };
}

const blankOffering = (key: string): OfferingDraft => ({
  key, name: "", description: "", delivery: "", availability: "", sku: "", quantity: "",
});
const blankSocial = (key: string): SocialAccountDraft => ({ key, platform: "", handle: "", url: "", notes: "" });

function pluralize(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

export function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  const { draft } = state;
  switch (action.type) {
    case "setCompanyName":
      return { ...state, draft: { ...draft, companyName: action.value } };

    case "setBusinessType": {
      const changed = draft.businessType !== null && draft.businessType !== action.value && draft.offerings.length > 0;
      return {
        ...state,
        draft: { ...draft, businessType: action.value },
        // Entries are kept; only the fields that belong to the new type apply.
        announcement: changed
          ? `Business type changed to ${BUSINESS_TYPE_META[action.value].label}. Your offerings are kept; review the fields that apply to this type.`
          : state.announcement,
      };
    }

    case "setPending":
      return state.pending[action.field] === action.value ? state : { ...state, pending: { ...state.pending, [action.field]: action.value } };

    case "addTags": {
      const rules = TAG_LABEL[action.field];
      const existing = draft[action.field];
      const merged = [...existing, ...action.tags.filter((tag) => !existing.some((item) => item.toLowerCase() === tag.toLowerCase()))].slice(0, rules.max);
      const added = merged.length - existing.length;
      if (added === 0) return state;
      return {
        ...state,
        draft: { ...draft, [action.field]: merged },
        pending: { ...state.pending, [action.field]: "" },
        announcement: `Added ${pluralize(added, rules.singular, rules.plural)}. ${pluralize(merged.length, rules.singular, rules.plural)} in the list.`,
      };
    }

    case "removeTag": {
      const rules = TAG_LABEL[action.field];
      const list = draft[action.field];
      if (action.index < 0 || action.index >= list.length) return state;
      const removed = list[action.index];
      return {
        ...state,
        draft: { ...draft, [action.field]: list.filter((_, index) => index !== action.index) },
        announcement: `Removed ${rules.singular} ${removed}. ${pluralize(list.length - 1, rules.singular, rules.plural)} left.`,
      };
    }

    case "addOffering": {
      if (draft.offerings.length >= LIMITS.maxOfferings) return state;
      const key = `offering-${state.keyCounter + 1}`;
      const noun = draft.businessType ? BUSINESS_TYPE_META[draft.businessType].offeringNoun : "offering";
      return {
        ...state,
        draft: { ...draft, offerings: [...draft.offerings, blankOffering(key)] },
        keyCounter: state.keyCounter + 1,
        focus: withFocus(state, "field", `offerings.${draft.offerings.length}.name`),
        announcement: `Added ${noun} ${draft.offerings.length + 1}.`,
      };
    }
    case "updateOffering":
      return {
        ...state,
        draft: { ...draft, offerings: draft.offerings.map((item) => (item.key === action.key ? { ...item, ...action.patch } : item)) },
      };
    case "removeOffering": {
      const index = draft.offerings.findIndex((item) => item.key === action.key);
      if (index < 0) return state;
      const remaining = draft.offerings.filter((item) => item.key !== action.key);
      return {
        ...state,
        draft: { ...draft, offerings: remaining },
        // Removing renumbers the list, so any per-row "touched" marks would point at the wrong row.
        touched: state.touched.filter((path) => !path.startsWith("offerings.")),
        focus: withFocus(state, "field", remaining.length > 0 ? `offerings.${Math.min(index, remaining.length - 1)}.name` : "offerings-add"),
        announcement: `Removed entry ${index + 1}. ${pluralize(remaining.length, "entry", "entries")} left.`,
      };
    }

    case "addSocial": {
      if (draft.socialAccounts.length >= LIMITS.maxSocialAccounts) return state;
      const key = `social-${state.keyCounter + 1}`;
      return {
        ...state,
        draft: { ...draft, socialAccounts: [...draft.socialAccounts, blankSocial(key)] },
        keyCounter: state.keyCounter + 1,
        focus: withFocus(state, "field", `socialAccounts.${draft.socialAccounts.length}.platform`),
        announcement: `Added account ${draft.socialAccounts.length + 1}. It is a plain detail and is not connected.`,
      };
    }
    case "updateSocial":
      return {
        ...state,
        draft: { ...draft, socialAccounts: draft.socialAccounts.map((item) => (item.key === action.key ? { ...item, ...action.patch } : item)) },
      };
    case "removeSocial": {
      const index = draft.socialAccounts.findIndex((item) => item.key === action.key);
      if (index < 0) return state;
      const remaining = draft.socialAccounts.filter((item) => item.key !== action.key);
      return {
        ...state,
        draft: { ...draft, socialAccounts: remaining },
        touched: state.touched.filter((path) => !path.startsWith("socialAccounts.")),
        focus: withFocus(state, "field", remaining.length > 0 ? `socialAccounts.${Math.min(index, remaining.length - 1)}.platform` : "socialAccounts-add"),
        announcement: `Removed account ${index + 1}. ${pluralize(remaining.length, "account", "accounts")} left.`,
      };
    }

    case "blur":
      return state.touched.includes(action.path) ? state : { ...state, touched: [...state.touched, action.path] };

    case "next": {
      const problems = wizardValidation(state).byStep[state.step];
      if (problems.length > 0) {
        return {
          ...state,
          attempted: state.attempted.includes(state.step) ? state.attempted : [...state.attempted, state.step],
          // Focus moves to the problem list, which is read out; a second live announcement would repeat it.
          focus: withFocus(state, "summary"),
        };
      }
      const next = STEP_IDS[Math.min(STEP_IDS.indexOf(state.step) + 1, STEP_IDS.length - 1)];
      return { ...state, step: next, focus: withFocus(state, "heading"), announcement: stepAnnouncement(next) };
    }

    case "back": {
      const previous = STEP_IDS[Math.max(STEP_IDS.indexOf(state.step) - 1, 0)];
      return { ...state, step: previous, focus: withFocus(state, "heading"), announcement: stepAnnouncement(previous) };
    }

    case "goto":
      return {
        ...state,
        step: action.step,
        focus: action.path ? withFocus(state, "field", action.path) : withFocus(state, "heading"),
        announcement: stepAnnouncement(action.step),
      };

    case "confirmAttempt": {
      const check = wizardValidation(state);
      if (check.complete) return state;
      return {
        ...state,
        attempted: state.attempted.includes("review") ? state.attempted : [...state.attempted, "review"],
        focus: withFocus(state, "summary"),
        announcement: `Cannot confirm yet: ${pluralize(check.errors.length, "item needs", "items need")} attention.`,
      };
    }

    case "loadSample": {
      const sample = buildSampleDraft((prefix, index) => `${prefix}-sample-${index}`);
      return {
        ...initialWizardState(),
        draft: sample,
        keyCounter: state.keyCounter + 10,
        focus: withFocus(state, "heading"),
        announcement: "Fictional sample data loaded. It is not real client information.",
      };
    }

    case "clear":
      return { ...initialWizardState(), keyCounter: state.keyCounter, focus: withFocus(state, "heading"), announcement: "Form cleared." };

    case "saveStarted":
      return { ...state, save: { status: "saving" }, announcement: "Saving." };
    case "saveSucceeded":
      return { ...state, save: { status: "saved" }, savedKey: action.key, announcement: "Profile saved." };
    case "saveFailed":
      return { ...state, save: { status: "error", code: action.code }, announcement: "Saving failed. Your entries are still here." };
    case "demoReviewed":
      return { ...state, demoReviewedKey: action.key, announcement: "Reviewed in demo mode. Nothing was saved or sent." };
  }
}

// ---------------------------------------------------------------------------
// Derived view helpers (pure)
// ---------------------------------------------------------------------------

export type StepStatus = "complete" | "needs_attention" | "incomplete" | "optional";

export function stepStatus(step: StepId, validation: ProfileValidation, state: WizardState): StepStatus {
  const problems = validation.byStep[step].length;
  if (step === "review") return validation.complete ? "complete" : state.attempted.includes("review") ? "needs_attention" : "incomplete";
  if (problems === 0) return step === "social" && state.draft.socialAccounts.length === 0 ? "optional" : "complete";
  return state.attempted.includes(step) ? "needs_attention" : "incomplete";
}

export type SaveView = "demo" | "unsaved" | "saving" | "saved" | "changed_since_saved" | "error";

/**
 * What the "saved profile" panel may claim. "saved" is only returned while the
 * form still equals what was saved; any edit turns it into changed_since_saved.
 */
export function saveView(state: WizardState, persistenceAvailable: boolean): SaveView {
  if (!persistenceAvailable) return "demo";
  if (state.save.status === "saving") return "saving";
  if (state.save.status === "error") return "error";
  const current = payloadKey(buildPayload(state.draft));
  if (state.savedKey !== null) return current === state.savedKey ? "saved" : "changed_since_saved";
  return "unsaved";
}

export function demoReviewedNow(state: WizardState): boolean {
  const current = payloadKey(buildPayload(state.draft));
  return current !== null && state.demoReviewedKey === current;
}

/** True when nothing has been typed yet, so replacing the form cannot lose work. */
export function isBlank(state: Pick<WizardState, "draft" | "pending">): boolean {
  const { draft, pending } = state;
  return (
    draft.companyName.trim() === "" &&
    draft.businessType === null &&
    draft.categories.length === 0 &&
    draft.segments.length === 0 &&
    draft.targetMarkets.length === 0 &&
    draft.offerings.length === 0 &&
    draft.socialAccounts.length === 0 &&
    Object.values(pending).every((text) => text.trim() === "")
  );
}
