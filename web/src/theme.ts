// The app's two tint colours. Everything tinted in styles.css (the accent, the glow blobs, the
// brand mark, the bars) is derived from --tint-a and --tint-b, so changing these two repaints
// the whole app.
//
// ponytail: saved in this browser only (localStorage). Move it to the server profile when the
// owner wants the same theme on every device.

import { useSyncExternalStore } from "react";

export type Theme = { a: string; b: string };

export const DEFAULT_THEME: Theme = { a: "#8b97ff", b: "#1dc4a0" };

export const PRESETS: { name: string; theme: Theme }[] = [
  { name: "Parity", theme: DEFAULT_THEME },
  { name: "Ocean", theme: { a: "#4fa3ff", b: "#2ee6d6" } },
  { name: "Sunset", theme: { a: "#ff7a59", b: "#ffc56b" } },
  { name: "Rose", theme: { a: "#ff6fa8", b: "#b18cff" } },
  { name: "Forest", theme: { a: "#4cc38a", b: "#c3e66e" } },
  { name: "Ember", theme: { a: "#ff5d5d", b: "#ffa94d" } },
  { name: "Lagoon", theme: { a: "#22c3e6", b: "#7cf29a" } },
  { name: "Grape", theme: { a: "#a46bff", b: "#ff7ad9" } },
  { name: "Slate", theme: { a: "#9aa8c4", b: "#d6deec" } },
  { name: "Citrus", theme: { a: "#f5c842", b: "#4cd6a0" } },
];

const KEY = "parity.theme";
const HEX = /^#[0-9a-f]{6}$/i;

/** Dark text on a light tint, white text on a dark one, so buttons stay readable. */
export function inkOn(hex: string): string {
  const n = Number.parseInt(hex.slice(1), 16);
  const [r, g, b] = [n >> 16, (n >> 8) & 255, n & 255] as const;
  // Perceived brightness (ITU-R BT.601 weights), 0 to 255. Colour maths, not money.
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#0b1020" : "#ffffff";
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement.style;
  root.setProperty("--tint-a", theme.a);
  root.setProperty("--tint-b", theme.b);
  root.setProperty("--on-tint", inkOn(theme.a));
}

export function loadTheme(): Theme {
  // Storage can be blocked (private windows), and a hand-edited value can be junk: fall back.
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "null") as Theme | null;
    if (saved && HEX.test(saved.a) && HEX.test(saved.b)) return saved;
  } catch {
    /* use the default */
  }
  return DEFAULT_THEME;
}

export function saveTheme(theme: Theme): void {
  applyTheme(theme);
  try {
    localStorage.setItem(KEY, JSON.stringify(theme));
  } catch {
    /* the theme still applies for this visit */
  }
}

// --- Light or dark ---------------------------------------------------------------------------
//
// "system" follows the device setting and changes with it; "light" and "dark" pin it. The
// choice is a data-theme attribute on <html> that styles.css reads.

export type Mode = "system" | "light" | "dark";
const MODE_KEY = "parity.mode";
const MODE_EVENT = "parity-mode"; // tells useIsDark the owner changed the setting

const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)");

export function loadMode(): Mode {
  try {
    const saved = localStorage.getItem(MODE_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* follow the system */
  }
  return "system";
}

export function applyMode(mode: Mode): void {
  if (mode === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = mode;
  window.dispatchEvent(new Event(MODE_EVENT));
}

export function saveMode(mode: Mode): void {
  applyMode(mode);
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch {
    /* it still applies for this visit */
  }
}

function isDark(): boolean {
  const pinned = document.documentElement.dataset.theme;
  return pinned ? pinned === "dark" : systemDark().matches;
}

/**
 * True while the app is showing dark. A React hook: a component that calls it redraws when the
 * owner flips the setting or, on "system", when the device switches between light and dark.
 * useSyncExternalStore is React's way to read a value that lives outside React.
 */
export function useIsDark(): boolean {
  return useSyncExternalStore((changed) => {
    const media = systemDark();
    media.addEventListener("change", changed);
    window.addEventListener(MODE_EVENT, changed);
    return () => {
      media.removeEventListener("change", changed);
      window.removeEventListener(MODE_EVENT, changed);
    };
  }, isDark);
}
