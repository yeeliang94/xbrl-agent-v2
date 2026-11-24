import { useCallback, useEffect, useState } from "react";
import { ApiError, errorMessage, type Guidance } from "../../api";
import { Button } from "../../components/Button";
import { Icon, IconButton } from "../../components/IconButton";
import { Panel } from "../../components/Panel";
import { TextInput } from "../../components/TextInput";
import "./GuidanceEditor.css";

export interface GuidanceEditorProps {
  title: string;
  load: () => Promise<Guidance>;
  /** Saves the whole list as a new version, based on the version shown. */
  save: (basedOn: number, lines: string[]) => Promise<Guidance>;
  readOnly?: boolean;
  /** Inside another panel: no panel of its own. */
  plain?: boolean;
}

/** A guidance list: each line with Remove, and a box to add one. Every change saves a new version. */
export function GuidanceEditor({ title, load, save, readOnly = false, plain = false }: GuidanceEditorProps) {
  const [guidance, setGuidance] = useState<Guidance | null>(null);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const reload = useCallback(async () => {
    try {
      setGuidance(await load());
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }, [load]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function change(lines: string[]) {
    if (!guidance) return;
    setSaving(true);
    setError("");
    try {
      setGuidance(await save(guidance.version, lines));
      setTyped("");
    } catch (failure) {
      setError(errorMessage(failure));
      // Someone else saved first: show their version.
      if (failure instanceof ApiError && failure.status === 409) await reload();
    } finally {
      setSaving(false);
    }
  }

  const lines = guidance?.lines ?? [];
  const body = (
    <>
      <div className="line">
        {plain ? <h3>{title}</h3> : <h2>{title}</h2>}
        {error && (
          <span className="error" role="alert">
            {error}
          </span>
        )}
      </div>
      {guidance && lines.length === 0 && readOnly && <p className="meta">No guidance</p>}
      {lines.map((text, index) => (
        <div className="gl" key={text}>
          <span>{text}</span>
          {!readOnly && (
            <IconButton label={`Remove "${text}"`} disabled={saving} onClick={() => change(lines.filter((_, i) => i !== index))}>
              <Icon name="close" />
            </IconButton>
          )}
        </div>
      ))}
      {!readOnly && guidance && (
        <div className="bar">
          <TextInput
            className="gl-add"
            aria-label={`Add to ${title.toLowerCase()}`}
            placeholder="Add guidance"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && typed.trim() && change([...lines, typed.trim()])}
          />
          <Button disabled={saving || !typed.trim()} onClick={() => change([...lines, typed.trim()])}>
            Add
          </Button>
        </div>
      )}
    </>
  );
  return plain ? <section className="sec guidance">{body}</section> : <Panel className="sec">{body}</Panel>;
}
