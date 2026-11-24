// A very small hash router. Hash addresses work however the server serves
// web/dist, so the server needs no fallback route.
import { useEffect, useState } from "react";

export type Route =
  | { name: "runs" }
  | { name: "new-run" }
  | { name: "setup"; runId: number }
  | { name: "run"; runId: number }
  | { name: "settings" };

export function routeFromHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/");
  if (parts[0] === "settings") return { name: "settings" };
  if (parts[0] === "runs" && parts[1] === "new") return { name: "new-run" };
  if (parts[0] === "runs" && /^\d+$/.test(parts[1] ?? "") && parts[2] === "setup") {
    return { name: "setup", runId: Number(parts[1]) };
  }
  if (parts[0] === "runs" && /^\d+$/.test(parts[1] ?? "") && parts.length === 2) {
    return { name: "run", runId: Number(parts[1]) };
  }
  return { name: "runs" };
}

export function hrefFor(route: Route): string {
  switch (route.name) {
    case "new-run":
      return "#/runs/new";
    case "setup":
      return `#/runs/${route.runId}/setup`;
    case "run":
      return `#/runs/${route.runId}`;
    default:
      return `#/${route.name}`;
  }
}

export function navigate(route: Route): void {
  window.location.hash = hrefFor(route);
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => routeFromHash(window.location.hash));
  useEffect(() => {
    const update = () => setRoute(routeFromHash(window.location.hash));
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}
