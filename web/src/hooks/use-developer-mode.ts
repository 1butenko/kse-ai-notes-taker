"use client";

import { useCallback, useSyncExternalStore } from "react";

const KEY = "kse-notes:developer-mode";
const listeners = new Set<() => void>();

function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false; // Storage can be blocked; the mode then stays off.
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/** Developer mode: shows the AI Note Taker's technical output. Off by default; remembered per browser. */
export function useDeveloperMode(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, read, () => false);
  const set = useCallback((next: boolean) => {
    try {
      window.localStorage.setItem(KEY, next ? "1" : "0");
    } catch {
      // Not remembered; nothing else to do.
    }
    listeners.forEach((listener) => listener());
  }, []);
  return [on, set];
}
