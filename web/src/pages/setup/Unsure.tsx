/** The orange dot: the Reader could not settle this from the page. */
export function Unsure({ reason }: { reason?: string }) {
  return <span className="unsure" role="img" aria-label="Check this" title={reason || "Check this"} />;
}
