import { useRef, type KeyboardEvent } from "react";
import "./Segmented.css";

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
}

export interface SegmentedProps<T extends string> {
  label: string;
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
}

/** A row of choices where exactly one is on. Arrow keys move between them. */
export function Segmented<T extends string>({ label, options, value, onChange, disabled }: SegmentedProps<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  // With nothing chosen yet, the first choice is the one in the tab order.
  const chosen = options.some((option) => option.value === value);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    let next: number | undefined;
    if (step) next = (index + step + options.length) % options.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = options.length - 1;
    if (next === undefined) return;
    event.preventDefault();
    onChange(options[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map((option, index) => {
        const on = option.value === value;
        return (
          <button
            key={option.value}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={on || (!chosen && index === 0) ? 0 : -1}
            className={on ? "on" : undefined}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
