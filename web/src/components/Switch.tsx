import type { KeyboardEvent } from "react";
import "./Switch.css";

export interface SwitchProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  id?: string;
}

/** One on/off switch for the whole app. Space and Enter toggle it. */
export function Switch({ label, checked, onChange, disabled, id }: SwitchProps) {
  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== " " && event.key !== "Enter") return;
    // Handle the key here and stop the browser's own click, so it toggles once.
    event.preventDefault();
    if (!disabled) onChange(!checked);
  }

  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={checked ? "switch on" : "switch"}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      onKeyDown={onKeyDown}
      onKeyUp={(event) => {
        if (event.key === " ") event.preventDefault();
      }}
    />
  );
}
