import "./Count.css";

/** A small number beside a label. Nothing is shown for zero. */
export function Count({ value }: { value: number }) {
  if (!value) return null;
  return <span className="cnt">{value}</span>;
}
