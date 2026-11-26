import { useState } from "react";
import { api, errorMessage, type ConnectionResult, type LoginLimits, type Model, type ModelRole } from "../../api";
import { Button } from "../../components/Button";
import { Panel } from "../../components/Panel";
import { Select, type SelectOption } from "../../components/Select";
import { Spinner } from "../../components/Spinner";
import { Status } from "../../components/Status";
import { SettingsLoading, type SettingsData } from "./useSettingsData";

const ROLES: { role: ModelRole; label: string }[] = [
  { role: "reading", label: "Reading" },
  { role: "extraction", label: "Extraction" },
  { role: "review", label: "Review" },
];

const minutes = (m: number) => (m % 60 === 0 ? `${m / 60} hour${m === 60 ? "" : "s"}` : `${m} minutes`);
const LOGIN: { field: keyof LoginLimits; label: string; values: number[]; text: (n: number) => string }[] = [
  { field: "idle_timeout_minutes", label: "Sign out after idle", values: [15, 30, 60, 120, 240, 480, 1440], text: minutes },
  { field: "max_attempts", label: "Attempts before lockout", values: [3, 5, 10, 20], text: String },
  { field: "lockout_minutes", label: "Lockout time", values: [5, 15, 30, 60, 240], text: minutes },
];

/** The choices for a sign-in limit, keeping a saved value that is not among them. */
function limitOptions(values: number[], current: number, text: (n: number) => string): SelectOption[] {
  const all = values.includes(current) ? values : [...values, current].sort((a, b) => a - b);
  return all.map((n) => ({ value: String(n), label: text(n) }));
}

/** The model list, keeping the saved model even if the provider no longer lists it. */
function modelOptions(models: Model[], current: string): SelectOption[] {
  const options = models.map((model) => ({ value: model.id, label: model.label, disabled: !model.available }));
  return options.some((option) => option.value === current) ? options : [{ value: current, label: current }, ...options];
}

type Test = { state: "idle" } | { state: "testing" } | { state: "done"; results: ConnectionResult[] } | { state: "failed"; message: string };

/** Sign-in limits, models and the connection test. Admins only. */
export function SystemTab({ data }: { data: SettingsData }) {
  const { settings, models, save, failure } = data;
  const [test, setTest] = useState<Test>({ state: "idle" });

  if (!settings) return <SettingsLoading data={data} />;
  const unknownFamily = (id: string) => models.find((m) => m.id === id)?.family === "other";
  const inUse = [...new Set(ROLES.map(({ role }) => settings.models[role]))];

  async function testConnection() {
    setTest({ state: "testing" });
    try {
      setTest({ state: "done", results: await api.testConnection() });
    } catch (problem) {
      setTest({ state: "failed", message: errorMessage(problem) });
    }
  }

  return (
    <>
      <Panel title="Sign-in">
        {LOGIN.map(({ field, label, values, text }) => (
          <div className="line" key={field}>
            <span>{label}</span>
            {failure(field)}
            <div className="ctl">
              <Select aria-label={label} options={limitOptions(values, settings.login[field], text)} value={String(settings.login[field])} onChange={(v) => save(field, { login: { [field]: Number(v) } })} />
            </div>
          </div>
        ))}
      </Panel>

      <Panel title="Models">
        <div className="line">
          <span>Set-up</span>
          <span className="ctl">{settings.route === "gateway" ? "Gateway" : "Direct"}</span>
        </div>
        {ROLES.map(({ role, label }) => (
          <div className="line" key={role}>
            <span>
              {label}
              {unknownFamily(settings.models[role]) && <span className="meta"> Not a recognised model family. Default settings are used.</span>}
            </span>
            {failure(role)}
            <div className="ctl">
              <Select aria-label={label} options={modelOptions(models, settings.models[role])} value={settings.models[role]} onChange={(id) => save(role, { models: { [role]: id } })} />
            </div>
          </div>
        ))}
      </Panel>

      <Panel className="sec" aria-label="Connection">
        <div className="line">
          <h2>Connection</h2>
          <Button size="small" disabled={test.state === "testing"} onClick={testConnection}>
            Test connection
          </Button>
        </div>
        {test.state === "testing" &&
          inUse.map((model) => (
            <div className="line" key={model}>
              <span>{model}</span>
              <Spinner small />
            </div>
          ))}
        {test.state === "done" &&
          test.results.map((result) => (
            <div className="line" key={result.model}>
              <span>{result.model}</span>
              {result.ok ? (
                <Status kind="finished">{result.sentence}</Status>
              ) : (
                <>
                  <span className="error">{result.sentence}</span>
                  <Status kind="failure">Failed</Status>
                </>
              )}
            </div>
          ))}
        {test.state === "failed" && (
          <p className="error" role="alert">
            {test.message}
          </p>
        )}
      </Panel>

    </>
  );
}
