import { useRef, useState, type DragEvent } from "react";
import { api, errorMessage } from "../api";
import { Button } from "../components/Button";
import { Failure } from "../components/Failure";
import { Icon, IconButton } from "../components/IconButton";
import { Panel } from "../components/Panel";
import { Status } from "../components/Status";
import { navigate } from "../router";
import "./NewRunPage.css";

/** The files a run can start from. The server decides from the file's content; this only filters the chooser. */
export const ACCEPT = ".pdf,.docx,.xlsx";
/** How many files upload at once (v1's limit; the job queue also reads two at a time). */
const AT_ONCE = 2;

const TYPES: Record<string, string> = { pdf: "PDF", docx: "Word document", xlsx: "Excel workbook" };

export function fileType(name: string): string {
  return TYPES[name.split(".").pop()?.toLowerCase() ?? ""] ?? "";
}

export function fileSize(bytes: number): string {
  return `${Math.max(0.1, bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface Item {
  file: File;
  state: "waiting" | "uploading" | "uploaded" | "refused";
  runId?: number;
  refusal?: string;
}

function ItemStatus({ item }: { item: Item }) {
  if (item.state === "refused") return <Status kind="failure">Refused</Status>;
  if (item.state === "uploaded") return <Status kind="finished">Uploaded</Status>;
  if (item.state === "uploading") return <Status kind="working">Uploading</Status>;
  return <Status kind="neutral">Waiting</Status>;
}

/** Choose one file, or several, to start runs from. One file goes on to its setup page; several each
 * become their own run waiting at setup. */
export function NewRunPage() {
  const input = useRef<HTMLInputElement>(null);
  const [chosen, setChosen] = useState<File[]>([]);
  const [single, setSingle] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [error, setError] = useState("");
  const [over, setOver] = useState(false);
  const all = useRef<Item[]>([]);
  const working = useRef(0);

  const started = items.length > 0;
  const done = started && items.every((item) => item.state === "uploaded" || item.state === "refused");
  const good = items.filter((item) => item.state === "uploaded").length;

  function change(item: Item, next: Partial<Item>) {
    Object.assign(item, next);
    setItems([...all.current]);
  }

  /** Upload what is waiting, at most two at a time, until nothing waits. */
  async function work() {
    working.current += 1;
    for (let item = all.current.find((i) => i.state === "waiting"); item; item = all.current.find((i) => i.state === "waiting")) {
      change(item, { state: "uploading" });
      try {
        const { run } = await api.upload(item.file);
        change(item, { state: "uploaded", runId: run.id });
      } catch (failure) {
        change(item, { state: "refused", refusal: errorMessage(failure) });
      }
    }
    working.current -= 1;
  }

  function startSeveral(files: File[]) {
    all.current = [...all.current, ...files.map((file) => ({ file, state: "waiting" as const }))];
    setItems([...all.current]);
    setChosen([]);
    // Start only the missing workers: one that finds nothing waiting stops at once.
    for (let more = AT_ONCE - working.current; more > 0; more -= 1) void work();
  }

  async function uploadOne(file: File) {
    setError("");
    setSingle(true);
    try {
      const { run } = await api.upload(file);
      navigate({ name: "setup", runId: run.id });
    } catch (failure) {
      setError(errorMessage(failure));
      setSingle(false);
      setChosen([]);
    }
  }

  function add(list: FileList | null | undefined) {
    const files = Array.from(list ?? []);
    if (input.current) input.current.value = "";
    if (!files.length || single) return;
    setError("");
    if (started) startSeveral(files);
    else setChosen((old) => [...old, ...files]);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setOver(false);
    add(event.dataTransfer.files);
  }

  const chooser = <input ref={input} type="file" accept={ACCEPT} multiple aria-label="PDF, Word or Excel files" hidden onChange={(event) => add(event.target.files)} />;

  if (started) {
    const at = Math.min(items.filter((item) => item.state !== "waiting").length, items.length);
    return (
      <>
        <div className="page-header">
          <h1>New run</h1>
          <span className="spacer" />
          {done && (
            <Button variant="primary" onClick={() => navigate({ name: "runs" })}>
              View runs
            </Button>
          )}
        </div>
        <div className="narrow">
          <Panel className="sec">
            <div className="line">
              <h2>{done ? (good === 0 ? "No runs started" : `${good} ${good === 1 ? "run" : "runs"} waiting at setup`) : `Uploading ${at} of ${items.length}`}</h2>
              {done && (
                <Button size="small" onClick={() => input.current?.click()}>
                  Add more files
                </Button>
              )}
            </div>
            <div className="files">
              {items.map((item, index) => (
                <div className="file" key={index}>
                  <div>
                    {item.file.name}
                    {item.refusal && <div role="alert" className="meta">{item.refusal}</div>}
                  </div>
                  <span className="meta mono r">{fileSize(item.file.size)}</span>
                  <span>
                    <ItemStatus item={item} />
                  </span>
                  <span className="end">
                    {item.runId !== undefined && (
                      <Button size="small" onClick={() => navigate({ name: "setup", runId: item.runId! })}>
                        Set up
                      </Button>
                    )}
                  </span>
                </div>
              ))}
            </div>
            {chooser}
          </Panel>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-header">
        <h1>New run</h1>
      </div>
      <div className="narrow">
        {error && <Failure label="Not uploaded">{error}</Failure>}
        <Panel>
          {chosen.length > 0 ? (
            <div className="sec">
              {chosen.map((file, index) => (
                <div className="line" key={index}>
                  <span>{file.name}</span>
                  <span className="meta">{fileType(file.name)}</span>
                  <span className="meta mono">{fileSize(file.size)}</span>
                  {single ? (
                    <Status kind="working">Uploading</Status>
                  ) : (
                    <IconButton label={`Remove ${file.name}`} onClick={() => setChosen(chosen.filter((_, i) => i !== index))}>
                      <Icon name="close" />
                    </IconButton>
                  )}
                </div>
              ))}
              {!single && (
                <div className="bar">
                  <span className="spacer" />
                  <Button variant="primary" onClick={() => (chosen.length > 1 ? startSeveral(chosen) : void uploadOne(chosen[0]))}>
                    {chosen.length > 1 ? `Start ${chosen.length} runs` : "Upload"}
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <div
              className={over ? "drop over" : "drop"}
              onDragOver={(event) => {
                event.preventDefault();
                setOver(true);
              }}
              onDragLeave={() => setOver(false)}
              onDrop={onDrop}
            >
              <div>
                <span>Drop a PDF, Word or Excel file</span>
                <Button onClick={() => input.current?.click()}>Choose file</Button>
              </div>
            </div>
          )}
          {chooser}
        </Panel>
      </div>
    </>
  );
}
