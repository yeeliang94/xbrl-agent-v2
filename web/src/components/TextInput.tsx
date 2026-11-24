import { forwardRef, type InputHTMLAttributes } from "react";
import "./Field.css";

export const TextInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function TextInput(
  { className, type = "text", ...rest },
  ref,
) {
  return <input ref={ref} type={type} className={["in", className ?? ""].filter(Boolean).join(" ")} {...rest} />;
});
