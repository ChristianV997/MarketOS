import { BUSINESS_TYPES, BUSINESS_TYPE_META, LIMITS } from "../contracts/clientProfileDraft.ts";
import { fieldId } from "../lib/validateProfile.ts";
import { TextField, WRAP } from "./Fields.tsx";
import { StepHeading, type StepProps } from "./StepChrome.tsx";

export function StepCompany({ state, dispatch, errorFor }: StepProps) {
  const { draft } = state;
  const typeError = errorFor("businessType");
  const typeId = fieldId("businessType");
  return (
    <div className="space-y-5">
      <StepHeading step="company">Tell us who this profile is for and how the business earns money.</StepHeading>

      <TextField
        path="companyName"
        label="Company name"
        required
        value={draft.companyName}
        maxLength={LIMITS.companyNameMax + 20}
        hint="The name customers know you by."
        error={errorFor("companyName")}
        onChange={(value) => dispatch({ type: "setCompanyName", value })}
        onBlur={() => dispatch({ type: "blur", path: "companyName" })}
      />

      <fieldset
        className="min-w-0 space-y-2"
        aria-describedby={[`${typeId}-hint`, typeError ? `${typeId}-error` : null].filter(Boolean).join(" ")}
      >
        <legend className="text-sm font-medium text-zinc-100">
          Business type <span aria-hidden="true" className="text-zinc-300">(required)</span>
        </legend>
        <p id={`${typeId}-hint`} className="text-xs text-zinc-400">
          This changes which questions appear later. You can change it without losing what you typed, but details that do not apply to the chosen type are not saved.
        </p>
        {BUSINESS_TYPES.map((type, index) => {
          const meta = BUSINESS_TYPE_META[type];
          const checked = draft.businessType === type;
          const inputId = index === 0 ? typeId : `${typeId}-${type}`;
          return (
            <label
              key={type}
              htmlFor={inputId}
              className={`flex min-h-[44px] cursor-pointer items-start gap-3 rounded border p-3 text-sm ${
                checked ? "border-sky-400 bg-sky-500/10" : "border-zinc-700 bg-zinc-900/60 hover:border-zinc-500"
              }`}
            >
              <input
                id={inputId}
                type="radio"
                name="businessType"
                value={type}
                checked={checked}
                className="mt-1 h-4 w-4 shrink-0 accent-sky-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400"
                onChange={() => dispatch({ type: "setBusinessType", value: type })}
                onBlur={() => dispatch({ type: "blur", path: "businessType" })}
              />
              <span className="min-w-0">
                <span className={`block font-medium text-zinc-100 ${WRAP}`}>{meta.label}</span>
                <span className={`block text-xs text-zinc-300 ${WRAP}`}>{meta.description}</span>
              </span>
            </label>
          );
        })}
        {typeError ? (
          <p id={`${typeId}-error`} data-field-error="businessType" className="text-sm text-red-300">
            <span className="font-semibold">Error: </span>
            {typeError}
          </p>
        ) : null}
      </fieldset>
    </div>
  );
}
