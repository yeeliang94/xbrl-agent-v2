import { useEffect, useState } from "react";
import { api, errorMessage, type HouseStyle, type LoginLimits, type Model, type ModelRole, type Settings, type SettingsChange, type User } from "../api";
import { Button } from "../components/Button";
import { Panel } from "../components/Panel";
import { Select, type SelectOption } from "../components/Select";
import { Switch } from "../components/Switch";
import { GuidanceEditor } from "./guidance/GuidanceEditor";

const loadFirm = () => api.firmGuidance().then((r) => r.guidance);
const saveFirm = (basedOn: number, lines: string[]) => api.saveFirmGuidance(basedOn, lines).then((r) => r.guidance);

const BODY_TEXT: SelectOption[] = [
  { value: "justified", label: "Justified" },
  { value: "left", label: "Left aligned" },
];
const TABLE_FONT: SelectOption[] = [9, 10, 11].map((pt) => ({ value: String(pt), label: `${pt} pt` }));
const SMALLEST_FONT: SelectOption[] = [8, 9].map((pt) => ({ value: String(pt), label: `${pt} pt` }));
const DOUBLE_UNDERLINE: SelectOption[] = [
  { value: "thick_bottom_border", label: "Thick bottom border" },
  { value: "single_bottom_border", label: "Single bottom border" },
];
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

export function SettingsPage({ user }: { user: User }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [models, setModels] = useState<Model[]>([]);
  const [error, setError] = useState("");
  // A failed save or download is shown beside the control it came from.
  const [failed, setFailed] = useState<{ key: string; message: string } | null>(null);
  const locked = !user.is_admin;

  useEffect(() => {
    let live = true;
    Promise.all([api.settings(), api.models()])
      .then(([loaded, list]) => {
        if (!live) return;
        setSettings(loaded);
        setModels(list);
      })
      .catch((failure) => live && setError(errorMessage(failure)));
    return () => {
      live = false;
    };
  }, []);

  async function run(key: string, work: () => Promise<void>) {
    setFailed(null);
    try {
      await work();
    } catch (failure) {
      setFailed({ key, message: errorMessage(failure) });
    }
  }

  const download = (key: string, fetchFile: () => Promise<void>) => run(key, fetchFile);
  const save = (key: string, change: SettingsChange) => run(key, async () => setSettings(await api.saveSettings(change)));

  /** The sentence of a failed save, beside its control. */
  const failure = (key: string) =>
    failed?.key === key ? (
      <span className="error" role="alert">
        {failed.message}
      </span>
    ) : null;

  // Each change sends only the field that changed; the server merges it.
  const style = (field: keyof HouseStyle, value: HouseStyle[keyof HouseStyle]) => save(field, { house_style: { [field]: value } });
  const model = (role: ModelRole, id: string) => save(role, { models: { [role]: id } });
  const unknownFamily = (id: string) => models.find((m) => m.id === id)?.family === "other";

  return (
    <>
      <div className="page-header">
        <h1>Settings</h1>
      </div>
      <div className="narrow">
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!settings && !error && <p className="empty">Loading settings</p>}
        {settings && locked && <p className="meta">Only an admin can change these settings.</p>}
        {settings && (
          <>
            <Panel title="Notes house style">
              <div className="line">
                <span>Body text</span>
                {failure("body_text")}
                <div className="ctl">
                  <Select aria-label="Body text" disabled={locked} options={BODY_TEXT} value={settings.house_style.body_text} onChange={(v) => style("body_text", v as HouseStyle["body_text"])} />
                </div>
              </div>
              <div className="line">
                <span>Table font size</span>
                {failure("table_font_pt")}
                <div className="ctl">
                  <Select aria-label="Table font size" disabled={locked} options={TABLE_FONT} value={String(settings.house_style.table_font_pt)} onChange={(v) => style("table_font_pt", Number(v) as HouseStyle["table_font_pt"])} />
                </div>
              </div>
              <div className="line">
                <span>Smallest table font</span>
                {failure("smallest_table_font_pt")}
                <div className="ctl">
                  <Select aria-label="Smallest table font" disabled={locked} options={SMALLEST_FONT} value={String(settings.house_style.smallest_table_font_pt)} onChange={(v) => style("smallest_table_font_pt", Number(v) as HouseStyle["smallest_table_font_pt"])} />
                </div>
              </div>
              <div className="line">
                <span>Double underline</span>
                {failure("double_underline")}
                <div className="ctl">
                  <Select aria-label="Double underline" disabled={locked} options={DOUBLE_UNDERLINE} value={settings.house_style.double_underline} onChange={(v) => style("double_underline", v as HouseStyle["double_underline"])} />
                </div>
              </div>
              <div className="line">
                <span>Bold totals</span>
                {failure("bold_totals")}
                <Switch label="Bold totals" disabled={locked} checked={settings.house_style.bold_totals} onChange={(on) => style("bold_totals", on)} />
              </div>
            </Panel>

            <GuidanceEditor title="Firm guidance" load={loadFirm} save={saveFirm} readOnly={locked} />

            <Panel title="Records">
              <div className="line">
                <span>Server logs, last 30 days</span>
                {failure("logs")}
                <Button size="small" disabled={locked} aria-label="Download server logs" onClick={() => download("logs", api.downloadLogs)}>
                  Download
                </Button>
              </div>
              <div className="line">
                <span>Usage and cost by run and day</span>
                {failure("usage")}
                <Button size="small" disabled={locked} aria-label="Download usage" onClick={() => download("usage", api.downloadUsage)}>
                  Download
                </Button>
              </div>
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
                    <Select aria-label={label} disabled={locked} options={modelOptions(models, settings.models[role])} value={settings.models[role]} onChange={(id) => model(role, id)} />
                  </div>
                </div>
              ))}
            </Panel>

            <Panel title="Workbench">
              <div className="line">
                <span>Code workbench</span>
                {failure("code_workbench")}
                <Switch label="Code workbench" disabled={locked} checked={settings.code_workbench} onChange={(on) => save("code_workbench", { code_workbench: on })} />
              </div>
              <div className="line">
                <span>Claude sandbox for real documents</span>
                {failure("claude_sandbox_real_documents")}
                <Switch label="Claude sandbox for real documents" disabled={locked} checked={settings.claude_sandbox_real_documents} onChange={(on) => save("claude_sandbox_real_documents", { claude_sandbox_real_documents: on })} />
              </div>
            </Panel>

            <Panel title="Sign-in">
              {LOGIN.map(({ field, label, values, text }) => (
                <div className="line" key={field}>
                  <span>{label}</span>
                  {failure(field)}
                  <div className="ctl">
                    <Select aria-label={label} disabled={locked} options={limitOptions(values, settings.login[field], text)} value={String(settings.login[field])} onChange={(v) => save(field, { login: { [field]: Number(v) } })} />
                  </div>
                </div>
              ))}
            </Panel>
          </>
        )}
      </div>
    </>
  );
}
