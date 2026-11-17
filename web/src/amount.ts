// The one place the web app turns typed text into minor units (cents).
//
// CLAUDE.md §6 forbids money maths in TypeScript, so this does none: it checks the text against
// a pattern and joins the digits. "12.5" -> "12" + "50" -> 1250. No floats, no rounding. Every
// figure shown on screen still comes from the Python API.
const AMOUNT = /^(\d{1,11})(?:\.(\d{1,2}))?$/;

/** "12.34" -> 1234, "40" -> 4000, "1,200.5" -> 120050. Returns null if it is not an amount. */
export function toMinor(text: string): number | null {
  const match = AMOUNT.exec(text.trim().replace(/^\$/, "").replaceAll(",", ""));
  if (!match) return null;
  const cents = (match[2] ?? "").padEnd(2, "0");
  return Number.parseInt(match[1] + cents, 10);
}
