import { api, type HouseStyle } from "../../api";
import { Button } from "../../components/Button";
import { Panel } from "../../components/Panel";
import { Select, type SelectOption } from "../../components/Select";
import { Switch } from "../../components/Switch";
import { GuidanceEditor } from "../guidance/GuidanceEditor";
import { SettingsLoading, type SettingsData } from "./useSettingsData";

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

/** Notes house style, firm guidance, records and the workbench. Read-only to someone who is not an admin. */
export function GeneralTab({ data, locked }: { data: SettingsData; locked: boolean }) {
  const { settings, save, run, failure } = data;
  if (!settings) return <SettingsLoading data={data} />;
  const style = (field: keyof HouseStyle, value: HouseStyle[keyof HouseStyle]) => save(field, { house_style: { [field]: value } });

  return (
    <>
      {locked && <p className="meta">Only an admin can change these settings.</p>}
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
          <Button size="small" disabled={locked} aria-label="Download server logs" onClick={() => run("logs", api.downloadLogs)}>
            Download
          </Button>
        </div>
        <div className="line">
          <span>Usage and cost by run and day</span>
          {failure("usage")}
          <Button size="small" disabled={locked} aria-label="Download usage" onClick={() => run("usage", api.downloadUsage)}>
            Download
          </Button>
        </div>
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
    </>
  );
}
