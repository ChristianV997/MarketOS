import { BUSINESS_TYPE_META } from "../contracts/clientProfileDraft.ts";
import { tagFieldRules } from "../lib/wizardState.ts";
import { ChipInput } from "./ChipInput.tsx";
import { StepHeading, type StepProps } from "./StepChrome.tsx";

export function StepAudience({ state, dispatch, errorFor }: StepProps) {
  const { draft } = state;
  const meta = draft.businessType ? BUSINESS_TYPE_META[draft.businessType] : null;
  const segmentsLabel = meta?.segmentsLabel ?? "Segments";
  return (
    <div className="space-y-6">
      <StepHeading step="audience">Who you serve and where. Short phrases work best.</StepHeading>
      {meta === null ? (
        <p role="note" className="rounded border border-amber-500/50 bg-amber-500/10 p-3 text-sm text-amber-100">
          Choose a business type in step 1 to get examples that fit. You can still fill this in now.
        </p>
      ) : null}

      <ChipInput
        path="categories"
        label="Categories"
        singular="category"
        plural="categories"
        hint={meta?.categoriesHint ?? "For example \"coffee equipment\" or \"bookkeeping\"."}
        values={draft.categories}
        text={state.pending.categories}
        onText={(value) => dispatch({ type: "setPending", field: "categories", value })}
        max={tagFieldRules("categories").max}
        error={errorFor("categories")}
        onAdd={(tags) => dispatch({ type: "addTags", field: "categories", tags })}
        onRemove={(index) => dispatch({ type: "removeTag", field: "categories", index })}
      />
      <ChipInput
        path="segments"
        label={segmentsLabel}
        singular="segment"
        plural="segments"
        required
        hint={meta?.segmentsHint ?? "Groups of customers or buyers you serve."}
        values={draft.segments}
        text={state.pending.segments}
        onText={(value) => dispatch({ type: "setPending", field: "segments", value })}
        max={tagFieldRules("segments").max}
        error={errorFor("segments")}
        onAdd={(tags) => dispatch({ type: "addTags", field: "segments", tags })}
        onRemove={(index) => dispatch({ type: "removeTag", field: "segments", index })}
      />
      <ChipInput
        path="targetMarkets"
        label="Target markets"
        singular="market"
        plural="markets"
        required
        hint={'Countries or regions you want to sell into, for example "Germany" or "Nordics".'}
        values={draft.targetMarkets}
        text={state.pending.targetMarkets}
        onText={(value) => dispatch({ type: "setPending", field: "targetMarkets", value })}
        max={tagFieldRules("targetMarkets").max}
        error={errorFor("targetMarkets")}
        onAdd={(tags) => dispatch({ type: "addTags", field: "targetMarkets", tags })}
        onRemove={(index) => dispatch({ type: "removeTag", field: "targetMarkets", index })}
      />
    </div>
  );
}
