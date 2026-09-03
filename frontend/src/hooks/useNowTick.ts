import { useEffect, useState } from "react";

/** Returns a one-second clock for live elapsed-time readouts. */
export function useNowTick(enabled = true): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [enabled]);

  return now;
}
