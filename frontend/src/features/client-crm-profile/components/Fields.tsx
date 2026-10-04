import type { ChangeEvent, ReactNode } from "react";
import { fieldId } from "../lib/validateProfile.ts";

export const INPUT_CLASS =
  "block w-full min-h-[44px] rounded border border-zinc-500 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400 aria-[invalid=true]:border-red-400";
export const BUTTON_PRIMARY =
  "inline-flex min-h-[44px] items-center justify-center rounded bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300 disabled:cursor-not-allowed disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:opacity-60";
export const BUTTON_SECONDARY =
  "inline-flex min-h-[44px] items-center justify-center rounded border border-zinc-600 bg-zinc-900 px-4 py-2 text-sm text-zinc-100 hover:border-zinc-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400 disabled:cursor-not-allowed disabled:opacity-50";
export const WRAP = "[overflow-wrap:anywhere]";

/** Label, hint and error wiring shared by every input so the aria links cannot drift. */
export function RequirementMarker({ required, marker }: { required?: boolean; marker?: "none" }) {
  if (marker === "none") return null;
  // The required state is also exposed through aria-required, so the visible word is hidden from assistive tech.
  return required ? <span aria-hidden="true" className="text-zinc-300"> (required)</span> : <span className="text-zinc-400"> (optional)</span>;
}

export function FieldFrame({
  path,
  label,
  required,
  marker,
  hint,
  error,
  children,
}: {
  path: string;
  label: string;
  required?: boolean;
  /** "none" drops the (required)/(optional) suffix when a group rule applies instead (handle or link). */
  marker?: "none";
  hint?: string;
  error?: string | null;
  children: (aria: { id: string; "aria-describedby": string | undefined; "aria-invalid": boolean | undefined; "aria-required": boolean | undefined }) => ReactNode;
}) {
  const id = fieldId(path);
  const describedBy = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="min-w-0 space-y-1">
      <label htmlFor={id} className="block text-sm font-medium text-zinc-100">
        {label}
        <RequirementMarker required={required} marker={marker} />
      </label>
      {hint ? <p id={`${id}-hint`} className={`text-xs text-zinc-400 ${WRAP}`}>{hint}</p> : null}
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined, "aria-required": required ? true : undefined })}
      {error ? (
        <p id={`${id}-error`} data-field-error={path} className={`text-sm text-red-300 ${WRAP}`}>
          <span className="font-semibold">Error: </span>
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function TextField({
  path,
  label,
  value,
  onChange,
  onBlur,
  required,
  marker,
  hint,
  error,
  maxLength,
  inputMode,
  multiline,
  placeholder,
  technical,
}: {
  path: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  required?: boolean;
  marker?: "none";
  hint?: string;
  error?: string | null;
  maxLength?: number;
  inputMode?: "text" | "numeric" | "url";
  multiline?: boolean;
  placeholder?: string;
  /** Handles, links, SKUs and numbers: no auto-capitalisation or spell-check. Names and prose keep the defaults. */
  technical?: boolean;
}) {
  return (
    <FieldFrame path={path} label={label} required={required} marker={marker} hint={hint} error={error}>
      {(aria) =>
        multiline ? (
          <textarea
            {...aria}
            name={path}
            rows={3}
            value={value}
            maxLength={maxLength}
            placeholder={placeholder}
            autoComplete="off"
            className={INPUT_CLASS}
            onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onChange(event.target.value)}
            onBlur={onBlur}
          />
        ) : (
          <input
            {...aria}
            name={path}
            type="text"
            value={value}
            maxLength={maxLength}
            inputMode={inputMode}
            placeholder={placeholder}
            autoComplete="off"
            autoCapitalize={technical ? "off" : undefined}
            spellCheck={technical ? false : undefined}
            className={INPUT_CLASS}
            onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
            onBlur={onBlur}
          />
        )
      }
    </FieldFrame>
  );
}

export function SelectField<T extends string>({
  path,
  label,
  value,
  options,
  onChange,
  onBlur,
  required,
  hint,
  error,
  placeholder = "Choose one",
}: {
  path: string;
  label: string;
  value: T | "";
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (value: T | "") => void;
  onBlur?: () => void;
  required?: boolean;
  hint?: string;
  error?: string | null;
  placeholder?: string;
}) {
  return (
    <FieldFrame path={path} label={label} required={required} hint={hint} error={error}>
      {(aria) => (
        <select
          {...aria}
          name={path}
          value={value}
          className={INPUT_CLASS}
          onChange={(event) => onChange(event.target.value as T | "")}
          onBlur={onBlur}
        >
          <option value="">{placeholder}</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      )}
    </FieldFrame>
  );
}
