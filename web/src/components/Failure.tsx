import { Panel } from "./Panel";
import { Status } from "./Status";

/** A failure on a screen: the dark-orange label and the server's sentence. */
export function Failure({ label, children }: { label: string; children: string }) {
  return (
    <Panel className="sec" role="alert">
      <div className="line">
        <span>
          <Status kind="failure">{label}</Status>
        </span>
      </div>
      <p>{children}</p>
    </Panel>
  );
}
