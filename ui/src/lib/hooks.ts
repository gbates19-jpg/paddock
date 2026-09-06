import { useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "../theme";

// Forces a re-render every `intervalMs` — used ONLY by things that must
// visibly age with no new event (countdowns, "ticks in the last 15s"
// rate displays). Everything else re-renders from store changes alone;
// reach for this sparingly.
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

// True for `durationMs` right after `value` changes, then false — used to
// trigger a one-shot flash (a value changed, then settles) instead of a
// continuous pulse. Off entirely under prefers-reduced-motion.
export function useFlash(value: unknown, durationMs = 700): boolean {
  const [flashing, setFlashing] = useState(false);
  const prev = useRef(value);
  useEffect(() => {
    if (prev.current === value) return;
    prev.current = value;
    if (prefersReducedMotion()) return;
    setFlashing(true);
    const id = setTimeout(() => setFlashing(false), durationMs);
    return () => clearTimeout(id);
  }, [value, durationMs]);
  return flashing;
}
