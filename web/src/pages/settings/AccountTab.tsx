import { useState, type FormEvent } from "react";
import { api, errorMessage, type User } from "../../api";
import { Button } from "../../components/Button";
import { Panel } from "../../components/Panel";
import { Status } from "../../components/Status";
import { TextInput } from "../../components/TextInput";
import { roleName, roleOf } from "./words";

/** Who is signed in, and a change of their own password. For everyone. */
export function AccountTab({ user }: { user: User }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState("");
  const [changed, setChanged] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setChanged(false);
    if (next !== repeat) {
      setError("The two new passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setRepeat("");
      setChanged(true);
    } catch (problem) {
      setError(errorMessage(problem));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Panel title={user.name || user.email}>
        <div className="kv">
          <span>Email</span>
          <span>{user.email}</span>
          <span>Role</span>
          <span>{roleName(roleOf(user))}</span>
        </div>
      </Panel>
      <Panel title="Password">
        <form className="form" onSubmit={submit}>
          <label className="field">
            <span>Current password</span>
            <TextInput type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
          </label>
          <label className="field">
            <span>New password</span>
            <TextInput type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
          </label>
          <label className="field">
            <span>New password again</span>
            <TextInput type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {changed && <Status kind="finished">Password changed</Status>}
          <Button type="submit" variant="primary" disabled={busy || !current || !next || !repeat}>
            Change password
          </Button>
        </form>
      </Panel>
    </>
  );
}
