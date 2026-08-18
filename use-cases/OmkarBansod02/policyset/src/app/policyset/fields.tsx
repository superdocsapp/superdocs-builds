"use client";

import { useId, type ChangeEvent, type ReactNode } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { splitList } from "./intake";

type FieldShellProps = {
  id: string;
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
};

function FieldShell({ id, label, hint, children, className }: FieldShellProps) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint ? <p className="text-xs leading-relaxed text-faint">{hint}</p> : null}
    </div>
  );
}

export function TextField({
  label,
  value,
  onChange,
  type = "text",
  hint,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "email" | "url" | "date";
  hint?: string;
  placeholder?: string;
}) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint}>
      <Input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="off"
      />
    </FieldShell>
  );
}

/**
 * Numbers carry their unit inside the control so the value never has to be
 * inferred from the label ("Return window  [ 30 ] days").
 */
export function NumberField({
  label,
  value,
  onChange,
  unit,
  min = 1,
  hint,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  unit?: string;
  min?: number;
  hint?: string;
}) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint}>
      <div className="relative">
        <Input
          id={id}
          type="number"
          min={min}
          inputMode="numeric"
          className={cn("tabular-nums", unit && "pr-16")}
          value={Number.isFinite(value) ? value : ""}
          onChange={(event: ChangeEvent<HTMLInputElement>) => {
            const next = event.target.valueAsNumber;
            onChange(Number.isFinite(next) ? next : 0);
          }}
        />
        {unit ? (
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[13px] text-muted"
          >
            {unit}
          </span>
        ) : null}
      </div>
    </FieldShell>
  );
}

export function TextAreaField({
  label,
  value,
  onChange,
  rows = 3,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  hint?: string;
}) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint}>
      <Textarea
        id={id}
        rows={rows}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </FieldShell>
  );
}

/**
 * Comma-separated entry, with a live read-only preview of how the value will
 * be parsed into the canonical profile.
 */
export function ListField({
  label,
  value,
  onChange,
  hint = "Separate entries with commas",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
}) {
  const id = useId();
  const entries = splitList(value);

  return (
    <FieldShell id={id} label={label} hint={entries.length === 0 ? hint : undefined}>
      <Input
        id={id}
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="off"
      />
      {entries.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5 pt-0.5">
          {entries.map((entry, index) => (
            <li
              key={`${entry}-${index}`}
              className="rounded-md border border-line bg-canvas px-1.5 py-0.5 text-[11px] leading-5 text-muted"
            >
              {entry}
            </li>
          ))}
        </ul>
      ) : null}
    </FieldShell>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  options,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
  hint?: string;
}) {
  const labelId = useId();
  return (
    <div className="space-y-1.5">
      <p id={labelId} className="text-[13px] font-medium leading-none text-ink-soft">
        {label}
      </p>
      <div
        role="group"
        aria-labelledby={labelId}
        className="grid grid-cols-2 gap-1 rounded-[var(--radius-control)] border border-line-strong bg-canvas p-1"
      >
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange(option.value)}
              className={cn(
                "h-7 rounded-[5px] text-[13px] font-medium transition-colors duration-150",
                selected
                  ? "bg-surface text-ink shadow-[0_1px_2px_rgb(23_23_27/0.08)]"
                  : "text-muted hover:text-ink",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      {hint ? <p className="text-xs leading-relaxed text-faint">{hint}</p> : null}
    </div>
  );
}

export function ToggleField({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-center justify-between gap-4 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2.5">
      <div className="min-w-0">
        <Label htmlFor={id} className="cursor-pointer">
          {label}
        </Label>
        {description ? (
          <p className="mt-0.5 text-xs text-faint">{description}</p>
        ) : null}
      </div>
      <input
        id={id}
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className={cn(
          "peer relative h-5 w-9 shrink-0 cursor-pointer appearance-none rounded-full bg-line-strong transition-colors duration-150",
          "before:absolute before:left-0.5 before:top-0.5 before:size-4 before:rounded-full before:bg-white before:shadow-sm before:transition-transform before:duration-150 before:content-['']",
          "checked:bg-accent checked:before:translate-x-4",
        )}
      />
    </div>
  );
}
