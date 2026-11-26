import { ROLES, type Role } from "./words";

/** The two roles, each with a line saying what it may do. Exactly one is on. */
export function RoleOptions({ value, onChange }: { value: Role; onChange: (role: Role) => void }) {
  return (
    <div className="opts" role="radiogroup" aria-label="Role">
      {ROLES.map((role) => {
        const on = role.id === value;
        return (
          <button key={role.id} type="button" role="radio" aria-checked={on} aria-label={role.name} className={on ? "opt on" : "opt"} onClick={() => onChange(role.id)}>
            <i aria-hidden="true" />
            <span>{role.name}</span>
            <span>{role.may}</span>
          </button>
        );
      })}
    </div>
  );
}
