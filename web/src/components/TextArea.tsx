import { forwardRef, type TextareaHTMLAttributes } from "react";
import "./Field.css";

export const TextArea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function TextArea(
  { className, ...rest },
  ref,
) {
  return <textarea ref={ref} className={["in", className ?? ""].filter(Boolean).join(" ")} {...rest} />;
});
