import { useState, type FormEvent } from "react";
import { api, errorMessage, type User } from "../api";
import { Button } from "../components/Button";
import { TextInput } from "../components/TextInput";
import { AuthLayout } from "./AuthLayout";

export function ChangePasswordPage({ onChanged, onLogout }: { onChanged: (user: User) => void; onLogout: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (next !== repeat) {
      setError("The new passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.changePassword(current, next);
      onChanged(await api.me());
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Change password" onSubmit={submit}>
      <label className="field">
        <span>Current password</span>
        <TextInput type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} autoFocus />
      </label>
      <label className="field">
        <span>New password</span>
        <TextInput type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
      </label>
      <label className="field">
        <span>Repeat new password</span>
        <TextInput type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <Button type="submit" variant="primary" disabled={busy || !current || !next || !repeat}>
        Change password
      </Button>
      <Button variant="quiet" onClick={onLogout}>
        Log out
      </Button>
    </AuthLayout>
  );
}
