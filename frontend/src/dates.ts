// Trip dates travel as "YYYY-MM-DD" strings in the user's local calendar (no time zone shifts).

export const MAX_DAYS_AHEAD = 365;

export function isoDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function fromIso(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(iso: string, days: number): string {
  const date = fromIso(iso);
  date.setDate(date.getDate() + days);
  return isoDate(date);
}

export const todayIso = () => isoDate(new Date());

export function formatDay(iso: string, lang: string, withWeekday = true): string {
  return fromIso(iso).toLocaleDateString(lang, {
    weekday: withWeekday ? "long" : undefined,
    day: "numeric",
    month: "long",
  });
}
