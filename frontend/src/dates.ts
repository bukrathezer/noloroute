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

/** "April" / "Nisan" for 4; "Apr" / "Nis" with `width` "short". */
export function monthName(month: number, lang: string, width: "long" | "short" = "long"): string {
  return new Date(2000, month - 1, 1).toLocaleDateString(lang, { month: width });
}

/** "Italy" / "İtalya" for "IT"; the code itself if the browser doesn't know it. */
export function countryName(code: string, lang: string): string {
  try {
    return new Intl.DisplayNames([lang], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** Day 1 of a trip in that month (1 = January): in the current month tomorrow (today on its last
 * day, so the trip stays in that month), otherwise the month's first day, this year or next. */
export function firstTripDayIn(month: number, today: string = todayIso()): string {
  const now = fromIso(today);
  if (now.getMonth() + 1 === month) {
    const tomorrow = addDays(today, 1);
    return fromIso(tomorrow).getMonth() === now.getMonth() ? tomorrow : today;
  }
  const year = month > now.getMonth() + 1 ? now.getFullYear() : now.getFullYear() + 1;
  return isoDate(new Date(year, month - 1, 1));
}

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
