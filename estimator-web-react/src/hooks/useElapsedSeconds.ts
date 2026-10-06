import { useEffect, useState } from "react";

/** Segundos transcurridos desde que `running` pasó a true; vuelve a 0 al empezar de nuevo. */
export function useElapsedSeconds(running: boolean): number {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    setSeconds(0);
    const interval = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [running]);

  return seconds;
}
