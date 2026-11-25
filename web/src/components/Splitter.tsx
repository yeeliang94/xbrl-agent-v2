import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import "./Splitter.css";

const STEP = 16;

/** A size token from tokens.css, in pixels, so the panels' sizes are set in one place. */
export function tokenPx(name: string, fallback: number): number {
  try {
    const value = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name));
    return Number.isFinite(value) ? value : fallback;
  } catch {
    return fallback;
  }
}

function stored(key: string): number | null {
  try {
    const value = Number(window.localStorage.getItem(key));
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

/** A panel's width the person can drag, kept between visits on this computer. Never below `min`. */
export function usePanelWidth(key: string, initial: number, min: number): [number, (width: number) => void] {
  const [width, setWidth] = useState(() => Math.max(min, stored(`panel:${key}`) ?? initial));
  const set = useCallback(
    (next: number) => {
      const value = Math.max(min, Math.round(next));
      setWidth(value);
      try {
        window.localStorage.setItem(`panel:${key}`, String(value));
      } catch {
        // A blocked store only means the width is not remembered.
      }
    },
    [key, min],
  );
  return [width, set];
}

export interface SplitterProps {
  label: string;
  /** The width of the panel this handle resizes. */
  width: number;
  min: number;
  /** The widest the panel may grow, worked out when a drag starts (so the other panel keeps its minimum). */
  max: () => number;
  /** "start": the panel is to the handle's left (the sidebar); "end": to its right (a side panel). */
  panel: "start" | "end";
  onChange: (width: number) => void;
  /** Draws a width while dragging, without saving it (the page is not redrawn on every step). Without it,
   * onChange gets every step. */
  onPreview?: (width: number) => void;
  /** Where the handle sits, as a CSS length from the container's left or right edge. */
  at: string;
}

/** The drag handle between two side-by-side panels. Arrow keys move it too. */
export function Splitter({ label, width, min, max, panel, onChange, onPreview, at }: SplitterProps) {
  const clamp = (value: number) => Math.min(Math.max(value, min), Math.max(min, max()));
  // A drag cut short (the page closes mid-drag) still lets go of the page.
  const release = useRef<(() => void) | null>(null);
  useEffect(() => () => release.current?.(), []);
  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const start = width;
    const target = event.currentTarget;
    target.setPointerCapture?.(event.pointerId);
    document.body.classList.add("resizing");
    let last = start;
    const most = max();
    const move = (e: globalThis.PointerEvent) => {
      const dx = e.clientX - startX;
      last = Math.min(Math.max(panel === "start" ? start + dx : start - dx, min), Math.max(min, most));
      (onPreview ?? onChange)(last);
    };
    const up = () => {
      if (onPreview && last !== start) onChange(last);
      document.body.classList.remove("resizing");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      release.current = null;
    };
    release.current = up;
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const grow = panel === "start" ? "ArrowRight" : "ArrowLeft";
    const shrink = panel === "start" ? "ArrowLeft" : "ArrowRight";
    if (event.key !== grow && event.key !== shrink) return;
    event.preventDefault();
    onChange(clamp(width + (event.key === grow ? STEP : -STEP)));
  }
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={min}
      aria-valuemax={Number.isFinite(max()) ? Math.round(max()) : undefined}
      tabIndex={0}
      className="splitter"
      style={panel === "start" ? { left: at } : { right: at }}
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
    />
  );
}

/** A main panel and a side panel on its right, with a handle between them. The side panel keeps its own
 * minimum, and the main panel keeps --work-min-w. Spread `style` and `ref` on the two-column container
 * (position: relative) and put `splitter` inside it. */
export function useSidePanel(key: string, widthToken: string, minToken: string) {
  // The container may appear after a loading screen, so it is tracked as it mounts, not read once.
  const node = useRef<HTMLDivElement | null>(null);
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const ref = useCallback((el: HTMLDivElement | null) => {
    node.current = el;
    setBox(el);
  }, []);
  // Sizes from tokens.css, read once.
  const [sizes] = useState(() => ({ min: tokenPx(minToken, 320), initial: tokenPx(widthToken, 420), work: tokenPx("--work-min-w", 480), gap: tokenPx("--space-4", 16) }));
  const { min } = sizes;
  const [width, setWidth] = usePanelWidth(key, sizes.initial, min);
  const max = () => (node.current?.clientWidth ?? Infinity) - sizes.work - sizes.gap;
  // A width kept from a wider space gives way, so the main panel keeps its minimum. The container is
  // watched, not the window: widening the sidebar narrows it too.
  useEffect(() => {
    const fit = () => {
      const most = Math.max(min, max());
      if (width > most) setWidth(most);
    };
    fit();
    if (!box || typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", fit);
      return () => window.removeEventListener("resize", fit);
    }
    const watch = new ResizeObserver(fit);
    watch.observe(box);
    return () => watch.disconnect();
    // max reads only the ref and the sizes, which never change.
  }, [box, width, min, setWidth]);
  const style = { [widthToken]: `${width}px` } as CSSProperties;
  const splitter = (
    <Splitter
      label="Side panel width"
      width={width}
      min={min}
      max={max}
      panel="end"
      onChange={setWidth}
      onPreview={(w) => node.current?.style.setProperty(widthToken, `${w}px`)}
      at={`calc(var(${widthToken}) + var(--space-4) / 2)`}
    />
  );
  return { ref, style, splitter };
}
