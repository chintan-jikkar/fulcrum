// Date text for headings. Dates arrive from the API as plain "YYYY-MM-DD" strings.

/** "2026-11-14" -> "Sat, Nov 14". Built from the parts so no timezone can shift the day. */
export function dayLabel(iso: string, today: string): string {
  if (iso === today) return "Today";
  const [y, m, d] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(new Date(y!, m! - 1, d!));
}

export function monthLabel(iso: string): string {
  const [y, m] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    year: "numeric",
  }).format(new Date(y!, m! - 1, 1));
}
