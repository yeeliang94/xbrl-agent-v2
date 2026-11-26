import { useEffect, useState, type ReactNode } from "react";
import { api, errorMessage, type Model, type Settings, type SettingsChange } from "../../api";

export interface SettingsData {
  settings: Settings | null;
  models: Model[];
  /** Why the settings could not be loaded, or "". */
  error: string;
  /** Runs a save or a download; a failure is shown beside the control with this key. */
  run: (key: string, work: () => Promise<void>) => Promise<void>;
  /** Each change sends only the field that changed; the server merges it. */
  save: (key: string, change: SettingsChange) => Promise<void>;
  /** The sentence of a failed save, beside its control. */
  failure: (key: string) => ReactNode;
}

/** The settings and the model list, loaded once for the General and System sections. */
export function useSettingsData(): SettingsData {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [models, setModels] = useState<Model[]>([]);
  const [error, setError] = useState("");
  const [failed, setFailed] = useState<{ key: string; message: string } | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([api.settings(), api.models()])
      .then(([loaded, list]) => {
        if (!live) return;
        setSettings(loaded);
        setModels(list);
      })
      .catch((problem) => live && setError(errorMessage(problem)));
    return () => {
      live = false;
    };
  }, []);

  async function run(key: string, work: () => Promise<void>) {
    setFailed(null);
    try {
      await work();
    } catch (problem) {
      setFailed({ key, message: errorMessage(problem) });
    }
  }

  const save = (key: string, change: SettingsChange) => run(key, async () => setSettings(await api.saveSettings(change)));

  const failure = (key: string) =>
    failed?.key === key ? (
      <span className="error" role="alert">
        {failed.message}
      </span>
    ) : null;

  return { settings, models, error, run, save, failure };
}

/** What the General and System sections show until the settings arrive. */
export function SettingsLoading({ data }: { data: SettingsData }) {
  if (data.error) {
    return (
      <p className="error" role="alert">
        {data.error}
      </p>
    );
  }
  return data.settings ? null : <p className="empty">Loading settings</p>;
}
