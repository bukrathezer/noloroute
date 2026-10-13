import type { DayPlan, PlannedStop } from "./api";
import type { Lang } from "./i18n";

/** A stop's name in the page's language (English when its Turkish name isn't known yet). */
export function stopName(stop: PlannedStop, lang: Lang): string {
  return (lang === "tr" && stop.name_tr) || stop.name;
}

/** The stops a day left out, named in the page's language. */
export function droppedNames(day: DayPlan, lang: Lang): string[] {
  const english = day.dropped_stops ?? [];
  const turkish = day.dropped_stops_tr ?? [];
  return lang === "tr" && turkish.length === english.length ? turkish : english;
}

/** A star rating with the language's decimal mark: "4.7" in English, "4,7" in Turkish. */
export function formatRating(rating: number, lang: Lang): string {
  return rating.toLocaleString(lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

/** Lowercase, accent-free form for search: "İstanbul", "ISTANBUL" and "istanbul" all match. */
export function searchKey(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "") // combining accents (also the dot of Turkish İ)
    .replace(/ı/g, "i") // Turkish dotless i
    .toLowerCase();
}
