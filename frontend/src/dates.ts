// Trip dates travel as "YYYY-MM-DD" strings in the user's local calendar (no time zone shifts).

export const MAX_DAYS_AHEAD = 365;

export function isoDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** Local midnight of an ISO day, for date pickers and formatting. */
export function fromIso(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(iso: string, days: number): string {
  const date = fromIso(iso);
  date.setDate(date.getDate() + days);
  return isoDate(date);
}

/** Whole days from one ISO day to another: 2026-10-10 → 2026-10-13 is 3. */
export function daysBetween(from: string, to: string): number {
  // Math.round absorbs the hour a daylight saving switch adds or removes.
  return Math.round((fromIso(to).getTime() - fromIso(from).getTime()) / 86_400_000);
}

export const todayIso = () => isoDate(new Date());

/** "September 2026" / "Eylül 2026". */
export function formatMonth(iso: string, lang: string): string {
  return fromIso(iso).toLocaleDateString(lang, { month: "long", year: "numeric" });
}

export function formatDay(iso: string, lang: string, withWeekday = true): string {
  return fromIso(iso).toLocaleDateString(lang, {
    weekday: withWeekday ? "long" : undefined,
    day: "numeric",
    month: "long",
  });
}

/** "Sat, Oct 10" / "10 Eki Cmt": compact enough for a date range on one line. */
export function formatShortDay(iso: string, lang: string): string {
  return fromIso(iso).toLocaleDateString(lang, { weekday: "short", day: "numeric", month: "short" });
}
