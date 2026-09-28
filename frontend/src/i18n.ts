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
    searchPlaceholder: "Search a hotel, address or place…",
    searching: "Searching…",
    noResults: "No matches. Try another name, or click on the map.",
    searchError: "Search isn't available right now. You can still click on the map.",
    orClickMap: "…or click on the map to drop a pin.",
    pinnedOnMap: "Pinned on the map",
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
    removeStop: (name: string) => `Remove ${name} from the route`,
    removeFailed: "Couldn't remove that stop. Please try again.",
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
  account: {
    login: "Log in",
    myRoutes: "My routes",
    logout: "Log out",
    signedInAs: (email: string) => `Signed in as ${email}`,
    deleteAccount: "Delete account",
    deleteWarning: "Your account and all your saved routes will be deleted permanently.",
    deletePassword: "Enter your password to confirm",
    deleteSubmit: "Delete my account",
    cancel: "Cancel",
    wrongPassword: "Wrong password.",
    deleteFailed: "Couldn't delete the account. Please try again.",
  },
  auth: {
    loginTitle: "Log in",
    registerTitle: "Create an account",
    saveHint: "Log in to save your route and find it again later.",
    email: "Email",
    password: "Password",
    passwordHint: "At least 8 characters",
    submitLogin: "Log in",
    submitRegister: "Create account",
    working: "Please wait…",
    toRegister: "No account yet? Create one",
    toLogin: "Already have an account? Log in",
    back: "← Back",
    errors: {
      wrongCredentials: "Wrong email or password.",
      emailTaken: "An account with this email already exists. Try logging in.",
      invalid: "Enter a valid email and a password of at least 8 characters.",
      tooMany: "Too many attempts. Please wait a few minutes and try again.",
    },
  },
  save: {
    button: "Save route",
    saving: "Saving…",
    saved: "Saved to My routes",
    saveChanges: "Save changes",
    error: "Couldn't save the route. Please try again.",
    defaultName: (city: string, days: number) => `${city} · ${days} ${days === 1 ? "day" : "days"}`,
  },
  saved: {
    title: "My routes",
    back: "← Back to planning",
    loading: "Loading your routes…",
    empty: "No saved routes yet. Plan a trip and press “Save route”.",
    loadError: "Couldn't load your routes.",
    meta: (days: number, stops: number) => `${days} ${days === 1 ? "day" : "days"} · ${stops} stops`,
    open: "Open",
    delete: "Delete",
    confirmDelete: (name: string) => `Delete “${name}”?`,
  },
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
    searchPlaceholder: "Otel, adres veya yer ara…",
    searching: "Aranıyor…",
    noResults: "Sonuç yok. Başka bir ad dene ya da haritaya tıkla.",
    searchError: "Arama şu an çalışmıyor. Haritaya tıklayarak da seçebilirsin.",
    orClickMap: "…ya da haritaya tıklayıp işaret koy.",
    pinnedOnMap: "Haritada işaretlenen konum",
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
    removeStop: (name) => `${name} durağını rotadan çıkar`,
    removeFailed: "Durak çıkarılamadı. Lütfen tekrar dene.",
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
  account: {
    login: "Giriş yap",
    myRoutes: "Rotalarım",
    logout: "Çıkış yap",
    signedInAs: (email) => `${email} olarak giriş yapıldı`,
    deleteAccount: "Hesabı sil",
    deleteWarning: "Hesabın ve kayıtlı bütün rotaların kalıcı olarak silinecek.",
    deletePassword: "Onaylamak için şifreni gir",
    deleteSubmit: "Hesabımı sil",
    cancel: "Vazgeç",
    wrongPassword: "Şifre hatalı.",
    deleteFailed: "Hesap silinemedi. Lütfen tekrar dene.",
  },
  auth: {
    loginTitle: "Giriş yap",
    registerTitle: "Hesap oluştur",
    saveHint: "Rotanı kaydedip sonra tekrar açabilmek için giriş yap.",
    email: "E-posta",
    password: "Şifre",
    passwordHint: "En az 8 karakter",
    submitLogin: "Giriş yap",
    submitRegister: "Hesap oluştur",
    working: "Lütfen bekle…",
    toRegister: "Hesabın yok mu? Kayıt ol",
    toLogin: "Zaten hesabın var mı? Giriş yap",
    back: "← Geri",
    errors: {
      wrongCredentials: "E-posta veya şifre hatalı.",
      emailTaken: "Bu e-postayla bir hesap zaten var. Giriş yapmayı dene.",
      invalid: "Geçerli bir e-posta ve en az 8 karakterlik bir şifre gir.",
      tooMany: "Çok fazla deneme yapıldı. Birkaç dakika bekleyip tekrar dene.",
    },
  },
  save: {
    button: "Rotayı kaydet",
    saving: "Kaydediliyor…",
    saved: "Rotalarım'a kaydedildi",
    saveChanges: "Değişiklikleri kaydet",
    error: "Rota kaydedilemedi. Lütfen tekrar dene.",
    defaultName: (city, days) => `${city} · ${days} gün`,
  },
  saved: {
    title: "Rotalarım",
    back: "← Planlamaya dön",
    loading: "Rotaların yükleniyor…",
    empty: "Henüz kayıtlı rotan yok. Bir gezi planlayıp “Rotayı kaydet”e bas.",
    loadError: "Rotaların yüklenemedi.",
    meta: (days, stops) => `${days} gün · ${stops} durak`,
    open: "Aç",
    delete: "Sil",
    confirmDelete: (name) => `“${name}” silinsin mi?`,
  },
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
