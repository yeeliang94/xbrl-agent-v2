import type { ButtonHTMLAttributes, ReactNode } from "react";
import "./Button.css";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "outline" | "quiet";
  size?: "normal" | "small";
  icon?: ReactNode;
}

export function Button({ variant = "outline", size = "normal", icon, className, children, type = "button", ...rest }: ButtonProps) {
  const classes = ["btn", variant, size === "small" ? "sm" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <button type={type} className={classes} {...rest}>
      {icon}
      {children}
    </button>
  );
}
