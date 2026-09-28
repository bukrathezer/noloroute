import type { City, TravelMode } from "./api";

export type Lang = "tr" | "en";

const en = {
  tagline: "Day-by-day routes planned around where you stay",
  switchLanguage: "Türkçe",
  city: {
    label: "City",
    placeholder: "Search a city…",
    clear: "Clear city",
    noResults: (supported: string) => `Not supported yet. Available: ${supported}`,
    places: (n: number) => `${n} places`,
  },
  hotel: {
    label: "Where are you staying?",
    pickCityFirst: "Pick a city first.",
    hint: "Click on the map to drop a pin at your hotel. You can drag it afterwards.",
    chosen: "Pin placed",
    useCenter: "Use the city centre",
    clear: "Remove pin",
  },
  days: { label: "Days", decrease: "Fewer days", increase: "More days" },
  mode: { label: "Getting around", WALK: "Walking", DRIVE: "Driving" } satisfies Record<TravelMode | "label", string>,
  budget: {
    label: "Entry-fee budget",
    optional: "optional",
    placeholder: "No limit",
  },
  submit: "Plan my trip",
  planning: "Planning…",
  result: {
    summary: (stops: number, days: number) => `${stops} stops over ${days} ${days === 1 ? "day" : "days"}`,
    allDays: "All days",
    day: (n: number) => `Day ${n}`,
    sightseeing: "Sightseeing",
    travel: "Travel",
    stopsCount: (n: number) => `${n} ${n === 1 ? "stop" : "stops"}`,
    entryCost: "Entry fees",
    unpriced: (n: number) => `${n} stops without price info`,
    visit: "visit",
    leg: (mode: string, duration: string, km: string, fromHotel: boolean) =>
      `${mode} ${duration} · ${km} km${fromHotel ? " from your hotel" : ""}`,
    backToHotel: "Back to your hotel",
    unknownCost: "—",
    estimated: "Approximate times: live routing was unavailable",
    emptyDay: "Nothing left to fit in this day.",
    focusDay: (n: number) => `Show only day ${n} on the map`,
  },
  errors: {
    network: "Can't reach the server. Check your connection and try again.",
    tooFar: "That pin is too far from the city's sights. Place it inside the city.",
    unknownCity: "This city isn't available.",
    generic: "Something went wrong while planning. Please try again.",
    loadCities: "Couldn't load the city list.",
  },
  categories: {
    MUSEUM: "Museum",
    LANDMARK: "Landmark",
    PARK: "Park",
    RELIGIOUS_SITE: "Religious site",
    VIEWPOINT: "Viewpoint",
    MARKET: "Market",
    OTHER: "Other",
  } as Record<string, string>,
  footer: { api: "API docs", source: "Source code" },
  minutes: (total: number) => formatDuration(total, "h", "min"),
};

type Strings = typeof en;

const tr: Strings = {
  tagline: "Kaldığın yere göre gün gün planlanan gezi rotaları",
  switchLanguage: "English",
  city: {
    label: "Şehir",
    placeholder: "Şehir ara…",
    clear: "Şehri temizle",
    noResults: (supported) => `Henüz desteklenmiyor. Mevcut şehirler: ${supported}`,
    places: (n) => `${n} yer`,
  },
  hotel: {
    label: "Nerede kalıyorsun?",
    pickCityFirst: "Önce bir şehir seç.",
    hint: "Otelinin yerini işaretlemek için haritaya tıkla. İşareti sonra sürükleyebilirsin.",
    chosen: "Konum işaretlendi",
    useCenter: "Şehir merkezini kullan",
    clear: "İşareti kaldır",
  },
  days: { label: "Gün sayısı", decrease: "Günü azalt", increase: "Günü artır" },
  mode: { label: "Ulaşım", WALK: "Yürüyerek", DRIVE: "Araçla" },
  budget: {
    label: "Giriş ücreti bütçesi",
    optional: "isteğe bağlı",
    placeholder: "Sınır yok",
  },
  submit: "Rotamı planla",
  planning: "Planlanıyor…",
  result: {
    summary: (stops, days) => `${days} günde ${stops} durak`,
    allDays: "Tüm günler",
    day: (n) => `${n}. gün`,
    sightseeing: "Gezme",
    travel: "Yol",
    stopsCount: (n) => `${n} durak`,
    entryCost: "Giriş ücretleri",
    unpriced: (n) => `${n} durağın fiyat bilgisi yok`,
    visit: "ziyaret",
    leg: (mode, duration, km, fromHotel) =>
      fromHotel
        ? `Otelden ${mode.toLocaleLowerCase("tr")} ${duration} · ${km} km`
        : `${mode} ${duration} · ${km} km`,
    backToHotel: "Otele dönüş",
    unknownCost: "—",
    estimated: "Yaklaşık süreler: canlı rota hesaplanamadı",
    emptyDay: "Bu güne sığacak yer kalmadı.",
    focusDay: (n) => `Haritada sadece ${n}. günü göster`,
  },
  errors: {
    network: "Sunucuya ulaşılamıyor. Bağlantını kontrol edip tekrar dene.",
    tooFar: "İşaret şehrin gezilecek yerlerinden çok uzakta. Şehrin içine yerleştir.",
    unknownCity: "Bu şehir mevcut değil.",
    generic: "Planlama sırasında bir sorun oluştu. Lütfen tekrar dene.",
    loadCities: "Şehir listesi yüklenemedi.",
  },
  categories: {
    MUSEUM: "Müze",
    LANDMARK: "Simge yapı",
    PARK: "Park",
    RELIGIOUS_SITE: "İbadet yeri",
    VIEWPOINT: "Seyir noktası",
    MARKET: "Çarşı ve pazar",
    OTHER: "Diğer",
  },
  footer: { api: "API dokümanı", source: "Kaynak kod" },
  minutes: (total) => formatDuration(total, "sa", "dk"),
};

export const STRINGS: Record<Lang, Strings> = { en, tr };

// Local names shown in the UI. City aliases for search will move to the database when more
// cities are added; until then this small table covers the two MVP cities.
const CITY_NAMES: Record<string, Partial<Record<Lang, string>>> = {
  istanbul: { tr: "İstanbul" },
};
const CITY_ALIASES: Record<string, string[]> = {
  istanbul: ["İstanbul", "Constantinople", "Estambul", "Stambul"],
  paris: ["París", "Parigi"],
};

export const cityName = (city: City, lang: Lang) => CITY_NAMES[city.id]?.[lang] ?? city.name;
export const cityAliases = (city: City) => [city.name, city.id, ...(CITY_ALIASES[city.id] ?? [])];

export function initialLang(): Lang {
  try {
    const saved = localStorage.getItem("lang");
    if (saved === "tr" || saved === "en") return saved;
  } catch {
    // Storage can be blocked (private mode); fall back to the browser language.
  }
  return navigator.language.toLowerCase().startsWith("tr") ? "tr" : "en";
}

function formatDuration(total: number, hourUnit: string, minuteUnit: string): string {
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  if (hours === 0) return `${minutes} ${minuteUnit}`;
  return minutes === 0 ? `${hours} ${hourUnit}` : `${hours} ${hourUnit} ${minutes} ${minuteUnit}`;
}
