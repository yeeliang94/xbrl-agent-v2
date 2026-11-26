import { useCallback, useEffect, useState } from "react";
import { api, setUnauthorizedHandler, type User } from "./api";
import { AppShell } from "./components/AppShell";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { LoginPage } from "./pages/LoginPage";
import { NewRunPage } from "./pages/NewRunPage";
import { RunsPage } from "./pages/RunsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { RunPage } from "./pages/run/RunPage";
import { SetupPage } from "./pages/setup/SetupPage";
import { hrefFor, useRoute } from "./router";

type Session = { state: "loading" } | { state: "out" } | { state: "in"; user: User };

export function App() {
  const [session, setSession] = useState<Session>({ state: "loading" });
  const [version, setVersion] = useState<string | null>(null);
  const route = useRoute();

  useEffect(() => {
    setUnauthorizedHandler(() => setSession({ state: "out" }));
    api
      .me()
      .then((user) => setSession({ state: "in", user }))
      .catch(() => setSession({ state: "out" }));
    api
      .version()
      .then(setVersion)
      .catch(() => {}); // the shell then shows no version
    return () => setUnauthorizedHandler(() => {});
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // The session is ended on this side either way.
    }
    setSession({ state: "out" });
  }, []);

  if (session.state === "loading") return null;
  if (session.state === "out") return <LoginPage onSignedIn={(user) => setSession({ state: "in", user })} />;

  const { user } = session;
  if (user.must_change_password) {
    return <ChangePasswordPage onChanged={(next) => setSession({ state: "in", user: next })} onLogout={logout} />;
  }

  return (
    <AppShell
      user={user}
      onLogout={logout}
      runId={route.name === "run" || route.name === "setup" ? route.runId : null}
      version={version}
      nav={[
        { href: hrefFor({ name: "runs" }), label: "Runs", active: route.name !== "settings" && route.name !== "run" },
        { href: hrefFor({ name: "settings" }), label: "Settings", active: route.name === "settings" },
      ]}
    >
      {route.name === "settings" && <SettingsPage user={user} />}
      {route.name === "runs" && <RunsPage user={user} />}
      {route.name === "new-run" && <NewRunPage />}
      {route.name === "setup" && <SetupPage key={route.runId} runId={route.runId} />}
      {route.name === "run" && <RunPage key={route.runId} runId={route.runId} user={user} />}
    </AppShell>
  );
}
