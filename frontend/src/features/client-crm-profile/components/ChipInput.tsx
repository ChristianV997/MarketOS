import { useRef, useState, type KeyboardEvent } from "react";
import { prepareTags } from "../lib/tags.ts";
import { fieldId } from "../lib/validateProfile.ts";
import { BUTTON_SECONDARY, INPUT_CLASS, RequirementMarker, WRAP } from "./Fields.tsx";

/**
 * Add-many text list (categories, segments, markets).
 * Enter or "Add" commits what was typed (commas and new lines split it); each
 * entry has its own remove button. Focus returns to the text box after adding
 * or removing so the next action is one keystroke away.
 */
export function ChipInput({
  path,
  label,
  singular,
  plural,
  hint,
  values,
  text,
  onText,
  max,
  required,
  error,
  onAdd,
  onRemove,
  onBlur,
}: {
  path: string;
  label: string;
  singular: string;
  plural: string;
  hint: string;
  values: readonly string[];
  /** Typed but not yet added. Held by the wizard so it is never lost silently. */
  text: string;
  onText: (value: string) => void;
  max: number;
  required?: boolean;
  /** Validation error for the whole list (for example "Add at least one category."). */
  error?: string | null;
  onAdd: (tags: string[]) => void;
  onRemove: (index: number) => void;
  onBlur?: () => void;
}) {
  const [localError, setLocalError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const id = fieldId(path);
  const shownError = localError ?? error ?? null;
  const describedBy = [`${id}-hint`, `${id}-list`, shownError ? `${id}-error` : null, note ? `${id}-note` : null].filter(Boolean).join(" ");

  function commit() {
    const result = prepareTags(text, values, singular[0].toUpperCase() + singular.slice(1), max);
    if (result.error) {
      setLocalError(result.error);
      setNote(null);
      return;
    }
    setLocalError(null);
    setNote(result.duplicates.length > 0 ? `Already in the list: ${result.duplicates.join(", ")}.` : null);
    if (result.accepted.length > 0) onAdd(result.accepted);
    onText("");
    inputRef.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
    event.preventDefault(); // Enter adds the entry; it must not submit the surrounding form
    commit();
  }

  return (
    <div className="min-w-0 space-y-2">
      <label htmlFor={id} className="block text-sm font-medium text-zinc-100">
        {label}
        <RequirementMarker required={required} />
      </label>
      <p id={`${id}-hint`} className={`text-xs text-zinc-400 ${WRAP}`}>
        {hint} Press Enter or choose Add. Separate several with commas.
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          ref={inputRef}
          id={id}
          name={path}
          type="text"
          value={text}
          autoComplete="off"
          spellCheck={false}
          aria-describedby={describedBy}
          aria-invalid={shownError ? true : undefined}
          aria-required={required ? true : undefined}
          className={INPUT_CLASS}
          onChange={(event) => {
            onText(event.target.value);
            if (localError) setLocalError(null);
            if (note) setNote(null);
          }}
          onKeyDown={onKeyDown}
          onBlur={onBlur}
        />
        <button type="button" className={`${BUTTON_SECONDARY} sm:shrink-0`} onClick={commit}>
          Add {singular}
        </button>
      </div>
      {shownError ? (
        <p id={`${id}-error`} role={localError ? "alert" : undefined} data-field-error={path} className={`text-sm text-red-300 ${WRAP}`}>
          <span className="font-semibold">Error: </span>
          {shownError}
        </p>
      ) : null}
      {note ? <p id={`${id}-note`} role="status" className="text-xs text-zinc-300">{note}</p> : null}
      <ul id={`${id}-list`} aria-label={`${label} added`} className="flex flex-wrap gap-2">
        {values.length === 0 ? <li className="text-xs text-zinc-400">None added yet.</li> : null}
        {values.map((value, index) => (
          <li key={`${value}-${index}`} className="flex min-w-0 items-center rounded border border-zinc-600 bg-zinc-900 pl-3 text-sm text-zinc-100">
            <span className={`min-w-0 ${WRAP}`}>{value}</span>
            <button
              type="button"
              aria-label={`Remove ${singular} ${value}`}
              className="ml-1 inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-r text-zinc-300 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
              onClick={() => {
                onRemove(index);
                setNote(null);
                inputRef.current?.focus();
              }}
            >
              <span aria-hidden="true">×</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="text-xs text-zinc-400">
        {values.length} of {max} {plural}.
      </p>
    </div>
  );
}
