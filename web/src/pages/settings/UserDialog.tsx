import { useState } from "react";
import { api, errorMessage, type AdminUser } from "../../api";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Status } from "../../components/Status";
import { RoleOptions } from "./RoleOptions";
import { firstName, roleOf, stamp, type Role } from "./words";

export interface UserDialogProps {
  user: AdminUser;
  /** The signed-in admin's own email: their password is changed on Account, not reset here. */
  ownEmail: string;
  onClose: () => void;
  /** The account after a change that the list must show. */
  onChanged: (user: AdminUser) => void;
  /** A new temporary password to show once. */
  onReset: (user: AdminUser, temporaryPassword: string) => void;
}

/** One user: change role, reset password, disable or enable. */
export function UserDialog({ user, ownEmail, onClose, onChanged, onReset }: UserDialogProps) {
  const [role, setRole] = useState<Role>(roleOf(user));
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  /** Runs one change. The server's refusal (the last admin, say) is shown in the dialog. */
  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (problem) {
      setError(errorMessage(problem));
      setConfirming(false);
      setBusy(false);
    }
  }

  const saveRole = () => act(async () => onChanged(await api.setAdmin(user.email, role === "admin")));
  const toggle = () => act(async () => onChanged(await (user.disabled ? api.enableUser(user.email) : api.disableUser(user.email))));
  const reset = () =>
    act(async () => {
      const result = await api.resetPassword(user.email);
      onReset(result.user, result.temporary_password);
    });

  if (confirming) {
    return (
      <Dialog
        open
        title={`Reset ${firstName(user)}'s password?`}
        onClose={onClose}
        actions={
          <>
            <Button variant="quiet" onClick={() => setConfirming(false)}>Cancel</Button>
            <Button variant="primary" disabled={busy} onClick={reset}>
              Reset password
            </Button>
          </>
        }
      >
        <p className="meta">The current password stops working straight away.</p>
      </Dialog>
    );
  }

  return (
    <Dialog
      open
      title={user.name || user.email}
      onClose={onClose}
      actions={
        <>
          {user.email !== ownEmail && (
            <Button variant="quiet" disabled={busy} onClick={() => setConfirming(true)}>
              Reset password
            </Button>
          )}
          <Button variant="quiet" disabled={busy} onClick={toggle}>
            {user.disabled ? "Enable" : "Disable"}
          </Button>
          <span className="spacer" />
          <Button variant="quiet" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={busy || role === roleOf(user)} onClick={saveRole}>
            Save role
          </Button>
        </>
      }
    >
      <div className="kv">
        <span>Email</span>
        <span>{user.email}</span>
        <span>Status</span>
        <Status kind={user.disabled ? "neutral" : "finished"}>{user.disabled ? "Disabled" : "Active"}</Status>
        <span>Last sign-in</span>
        <span>{user.last_sign_in_at ? stamp(user.last_sign_in_at) : "Never"}</span>
      </div>
      <RoleOptions value={role} onChange={setRole} />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}
