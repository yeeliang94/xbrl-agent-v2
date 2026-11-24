import "./Spinner.css";

export function Spinner({ small = false }: { small?: boolean }) {
  return <i className={small ? "spin sm" : "spin"} aria-hidden="true" />;
}
