import {
  BUSINESS_TYPE_META,
  LIMITS,
  PRODUCT_AVAILABILITY,
  SERVICE_DELIVERY_MODES,
} from "../contracts/clientProfileDraft.ts";
import { BUTTON_SECONDARY, SelectField, TextField, WRAP } from "./Fields.tsx";
import { StepHeading, type StepProps } from "./StepChrome.tsx";

const DELIVERY_OPTIONS = SERVICE_DELIVERY_MODES.map((value) => ({
  value,
  label: { remote: "Remote", on_site: "On site", hybrid: "Remote and on site" }[value],
}));
const AVAILABILITY_OPTIONS = PRODUCT_AVAILABILITY.map((value) => ({
  value,
  label: { in_stock: "In stock", made_to_order: "Made to order", dropship: "Dropshipped", preorder: "Pre-order", unknown: "Not sure" }[value],
}));

export function StepOfferings({ state, dispatch, errorFor }: StepProps) {
  const { draft } = state;
  const meta = draft.businessType ? BUSINESS_TYPE_META[draft.businessType] : null;
  const noun = meta?.offeringNoun ?? "product or service";
  const listError = errorFor("offerings");
  const blur = (path: string) => () => dispatch({ type: "blur", path });

  return (
    <div className="space-y-5">
      <StepHeading step="offerings">
        {meta?.tracksInventory
          ? "List what you sell. Stock details are optional and are your own unverified figures."
          : meta
            ? "List the services you provide. How each is delivered is optional."
            : "List what you sell or provide."}
      </StepHeading>
      {meta === null ? (
        <p role="note" className="rounded border border-amber-500/50 bg-amber-500/10 p-3 text-sm text-amber-100">
          Choose a business type in step 1 so the right questions appear. Delivery and availability are optional questions that appear once it is chosen.
        </p>
      ) : null}
      {meta && draft.offerings.length > 0 ? (
        <p role="note" data-type-note className="text-xs text-zinc-300">
          Business type: {meta.label}. {meta.tracksInventory ? "Availability is optional." : "Delivery is optional."} Details typed for another type are kept but not saved.
        </p>
      ) : null}
      {listError ? (
        <p id="cp-offerings-error" data-field-error="offerings" className={`text-sm text-red-300 ${WRAP}`}>
          <span className="font-semibold">Error: </span>
          {listError}
        </p>
      ) : null}

      <ol className="space-y-4">
        {draft.offerings.map((offering, index) => {
          const base = `offerings.${index}`;
          return (
            <li key={offering.key}>
              <fieldset className="min-w-0 space-y-3 rounded-lg border border-zinc-700 bg-zinc-900/40 p-3 sm:p-4">
                <legend className="px-1 text-sm font-semibold text-zinc-100">
                  {meta ? meta.offeringNoun[0].toUpperCase() + meta.offeringNoun.slice(1) : "Offering"} {index + 1}
                </legend>
                <TextField
                  path={`${base}.name`}
                  label="Name"
                  required
                  value={offering.name}
                  maxLength={LIMITS.offeringNameMax + 20}
                  error={errorFor(`${base}.name`)}
                  onChange={(value) => dispatch({ type: "updateOffering", key: offering.key, patch: { name: value } })}
                  onBlur={blur(`${base}.name`)}
                />
                <TextField
                  path={`${base}.description`}
                  label="Short description"
                  multiline
                  value={offering.description}
                  maxLength={LIMITS.offeringDescriptionMax + 50}
                  hint={`Up to ${LIMITS.offeringDescriptionMax} characters.`}
                  error={errorFor(`${base}.description`)}
                  onChange={(value) => dispatch({ type: "updateOffering", key: offering.key, patch: { description: value } })}
                  onBlur={blur(`${base}.description`)}
                />
                {meta && !meta.tracksInventory ? (
                  <SelectField
                    path={`${base}.delivery`}
                    label="How is it delivered?"
                    value={offering.delivery}
                    options={DELIVERY_OPTIONS}
                    error={errorFor(`${base}.delivery`)}
                    onChange={(value) => dispatch({ type: "updateOffering", key: offering.key, patch: { delivery: value } })}
                    onBlur={blur(`${base}.delivery`)}
                  />
                ) : null}
                {meta?.tracksInventory ? (
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                    <SelectField
                      path={`${base}.availability`}
                      label="Availability"
                      value={offering.availability}
                      options={AVAILABILITY_OPTIONS}
                      error={errorFor(`${base}.availability`)}
                      onChange={(value) => dispatch({ type: "updateOffering", key: offering.key, patch: { availability: value } })}
                      onBlur={blur(`${base}.availability`)}
                    />
                    <TextField
                      path={`${base}.sku`}
                      label="SKU"
                      technical
                      value={offering.sku}
                      maxLength={LIMITS.skuMax + 10}
                      hint="Your own product code."
                      error={errorFor(`${base}.sku`)}
                      onChange={(value) => dispatch({ type: "updateOffering", key: offering.key, patch: { sku: value } })}
                      onBlur={blur(`${base}.sku`)}
                    />
                    <TextField
                      path={`${base}.quantity`}
                      label="Units on hand"
                      technical
                      inputMode="numeric"
                      value={offering.quantity}
                      maxLength={10}
                      hint="Self-reported and not verified. Leave empty if unknown."
                      error={errorFor(`${base}.quantity`)}
                      onChange={(value) => dispatch({ type: "updateOffering", key: offering.key, patch: { quantity: value } })}
                      onBlur={blur(`${base}.quantity`)}
                    />
                  </div>
                ) : null}
                <button
                  type="button"
                  className={BUTTON_SECONDARY}
                  aria-label={`Remove ${noun} ${index + 1}${offering.name.trim() ? `: ${offering.name.trim()}` : ""}`}
                  onClick={() => dispatch({ type: "removeOffering", key: offering.key })}
                >
                  Remove
                </button>
              </fieldset>
            </li>
          );
        })}
      </ol>

      <button
        type="button"
        id="cp-offerings-add"
        aria-describedby={listError ? "cp-offerings-error" : undefined}
        className={BUTTON_SECONDARY}
        disabled={draft.offerings.length >= LIMITS.maxOfferings}
        onClick={() => dispatch({ type: "addOffering" })}
      >
        Add {noun}
      </button>
    </div>
  );
}
