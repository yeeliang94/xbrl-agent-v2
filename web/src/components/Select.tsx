import type { SelectHTMLAttributes } from "react";
import "./Field.css";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "onChange" | "value"> {
  options: SelectOption[];
  value: string;
  onChange: (value: string) => void;
}

/** One dropdown for the whole app: the browser's own, styled. */
export function Select({ options, value, onChange, className, ...rest }: SelectProps) {
  return (
    <select
      className={["in", className ?? ""].filter(Boolean).join(" ")}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      {...rest}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value} disabled={option.disabled}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
