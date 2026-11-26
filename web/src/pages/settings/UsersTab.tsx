import { useCallback, useEffect, useState } from "react";
import { api, errorMessage, type AdminUser, type User } from "../../api";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Panel } from "../../components/Panel";
import { Status } from "../../components/Status";
import { Table, type Column } from "../../components/Table";
import { TextInput } from "../../components/TextInput";
import { RoleOptions } from "./RoleOptions";
import { UserDialog } from "./UserDialog";
import { firstName, roleName, roleOf, stamp, type Role } from "./words";

const COLUMNS: Column<AdminUser>[] = [
  { key: "name", header: "Name", nowrap: true, render: (u) => u.name || u.email },
  { key: "email", header: "Email", muted: true, render: (u) => u.email },
  { key: "role", header: "Role", render: (u) => roleName(roleOf(u)) },
  { key: "status", header: "Status", render: (u) => <Status kind={u.disabled ? "neutral" : "finished"}>{u.disabled ? "Disabled" : "Active"}</Status> },
  { key: "last", header: "Last sign-in", muted: true, nowrap: true, render: (u) => (u.last_sign_in_at ? stamp(u.last_sign_in_at) : "Never") },
];

type Open = { kind: "add" } | { kind: "user"; email: string } | { kind: "temporary"; user: AdminUser; password: string } | null;

/** The people who may sign in. Admins only. */
export function UsersTab({ me }: { me: User }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<Open>(null);

  const load = useCallback(() => {
    setError("");
    setUsers(null);
    api
      .users()
      .then(setUsers)
      .catch((problem) => setError(errorMessage(problem)));
  }, []);
  useEffect(load, [load]);

  /** Puts a changed or new account into the list. */
  const keep = (user: AdminUser) =>
    setUsers((list) => {
      const rest = (list ?? []).filter((u) => u.email !== user.email);
      return [...rest, user].sort((a, b) => a.email.localeCompare(b.email));
    });

  if (error) {
    return (
      <Panel className="sec">
        <div className="line">
          <span className="error" role="alert">
            {error}
          </span>
          <Button size="small" onClick={load}>
            Try again
          </Button>
        </div>
      </Panel>
    );
  }
  if (users === null) return <p className="empty">Loading users</p>;
  const chosen = open?.kind === "user" ? users.find((u) => u.email === open.email) : undefined;

  return (
    <Panel className="sec">
      <div className="line">
        <h2>Users</h2>
        <Button variant="primary" onClick={() => setOpen({ kind: "add" })}>
          Add user
        </Button>
      </div>
      <Table columns={COLUMNS} rows={users} rowKey={(u) => u.email} onRowClick={(u) => setOpen({ kind: "user", email: u.email })} />
      {open?.kind === "add" && (
        <AddUserDialog
          onClose={() => setOpen(null)}
          onAdded={(user, password) => {
            keep(user);
            setOpen({ kind: "temporary", user, password });
          }}
        />
      )}
      {chosen && (
        <UserDialog
          user={chosen}
          ownEmail={me.email}
          onClose={() => setOpen(null)}
          onChanged={(user) => {
            keep(user);
            setOpen(null);
          }}
          onReset={(user, password) => {
            keep(user);
            setOpen({ kind: "temporary", user, password });
          }}
        />
      )}
      {open?.kind === "temporary" && <TemporaryPasswordDialog user={open.user} password={open.password} onClose={() => setOpen(null)} />}
    </Panel>
  );
}

function AddUserDialog({ onClose, onAdded }: { onClose: () => void; onAdded: (user: AdminUser, temporaryPassword: string) => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("preparer");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function add() {
    if (!name.trim() || !email.trim()) {
      setError("Enter a name and an email.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api.addUser(email.trim(), name.trim(), role === "admin");
      onAdded(result.user, result.temporary_password);
    } catch (problem) {
      setError(errorMessage(problem));
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      title="Add user"
      onClose={onClose}
      actions={
        <>
          <Button variant="quiet" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={busy} onClick={add}>
            Add user
          </Button>
        </>
      }
    >
      <label className="field">
        <span>Name</span>
        <TextInput value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field">
        <span>Email</span>
        <TextInput type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <RoleOptions value={role} onChange={setRole} />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}

/** The temporary password of a new or reset account. The server gives it once, so it is shown once. */
function TemporaryPasswordDialog({ user, password, onClose }: { user: AdminUser; password: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const who = firstName(user);

  async function copy() {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
    } catch {
      // The password stays on screen to be copied by hand.
    }
  }

  return (
    <Dialog
      open
      title={`Temporary password for ${who}`}
      onClose={onClose}
      actions={
        <Button variant="primary" onClick={onClose}>
          Done
        </Button>
      }
    >
      <div className="secret">
        <span>{password}</span>
        <Button size="small" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <p className="meta">
        This is shown once. {who} chooses a new password at first log in.
      </p>
    </Dialog>
  );
}
