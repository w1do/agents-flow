import type { ReactNode } from "react";
import { fieldLabels, type FieldName } from "./validation";

export interface ControlProps {
  id: string;
  "aria-invalid": boolean;
  "aria-describedby": string | undefined;
}

export function ProjectField({
  name,
  error,
  hint,
  children,
}: {
  name: FieldName;
  error?: string;
  hint?: string;
  children: (props: ControlProps) => ReactNode;
}) {
  const id = `field-${name}`;
  return (
    <div className="space-y-2">
      <label htmlFor={id}>{fieldLabels[name]}</label>
      {children({
        id,
        "aria-invalid": Boolean(error),
        "aria-describedby": error ? `${id}-error` : hint ? `${id}-hint` : undefined,
      })}
      {hint && (
        <p id={`${id}-hint`} className="hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="field-error">
          {error}
        </p>
      )}
    </div>
  );
}
