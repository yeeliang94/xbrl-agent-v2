import { useState, type FormEvent } from "react";
import { api, errorMessage, type User } from "../api";
import { Button } from "../components/Button";
import { TextInput } from "../components/TextInput";
import { AuthLayout } from "./AuthLayout";

export function LoginPage({ onSignedIn }: { onSignedIn: (user: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSignedIn(await api.login(email.trim(), password));
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Log in" onSubmit={submit}>
      <label className="field">
        <span>Email</span>
        <TextInput type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
      </label>
      <label className="field">
        <span>Password</span>
        <TextInput type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <Button type="submit" variant="primary" disabled={busy || !email.trim() || !password}>
        Log in
      </Button>
    </AuthLayout>
  );
}
