import { useEffect, useRef, useState } from "react";
import { ApiError, type City, fetchCities, type PlanResponse, planRoute } from "./api";
import { PlanForm, type FormState } from "./components/PlanForm";
import { PlanResult } from "./components/PlanResult";
import { RouteMap } from "./components/RouteMap";
import { initialLang, type Lang, STRINGS } from "./i18n";

const SOURCE_URL = "https://github.com/bukrathezer/noloroute";

export function App() {
  const [lang, setLang] = useState<Lang>(initialLang);
  const [cities, setCities] = useState<City[]>([]);
  const [citiesFailed, setCitiesFailed] = useState(false);
  const [form, setForm] = useState<FormState>({ city: null, hotel: null, days: 2, mode: "WALK", budget: "" });
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeDay, setActiveDay] = useState<number | null>(null);
  const [highlightedStop, setHighlightedStop] = useState<string | null>(null);
  // Ignores responses to requests that were superseded while in flight.
  const requestId = useRef(0);
  const t = STRINGS[lang];

  useEffect(() => {
    fetchCities()
      .then(setCities)
      .catch(() => setCitiesFailed(true));
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    try {
      localStorage.setItem("lang", lang);
    } catch {
      // Storage unavailable: the choice just won't be remembered.
    }
  }, [lang]);

  const updateForm = (patch: Partial<FormState>) => {
    setForm((f) => ({ ...f, ...patch }));
    // Any change makes the current plan stale.
    requestId.current++;
    setPlan(null);
    setError(null);
    setActiveDay(null);
    setLoading(false);
  };

  const submit = async () => {
    if (!form.city || !form.hotel) return;
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const budget = form.budget.trim() === "" ? undefined : Number(form.budget);
      const result = await planRoute({
        city_id: form.city.id,
        accommodation: form.hotel,
        duration_days: form.days,
        travel_mode: form.mode,
        budget,
      });
      if (id !== requestId.current) return;
      setPlan(result);
      setActiveDay(null);
    } catch (e) {
      if (id !== requestId.current) return;
      setError(errorMessage(e, lang));
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  };

  return (
    <div className="app">
      <aside className="panel">
        <header className="brand">
          <a className="logo" href="/">
            <img src="/favicon.svg" alt="" width={28} height={28} />
            <span>NoloRoute</span>
          </a>
          <button type="button" className="lang-toggle" onClick={() => setLang(lang === "tr" ? "en" : "tr")}>
            {t.switchLanguage}
          </button>
        </header>
        <p className="tagline">{t.tagline}</p>

        {citiesFailed && (
          <p className="error" role="alert">
            {t.errors.loadCities}
          </p>
        )}

        <PlanForm cities={cities} form={form} onChange={updateForm} onSubmit={submit} loading={loading} lang={lang} />

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        {plan && (
          <PlanResult
            plan={plan}
            lang={lang}
            activeDay={activeDay}
            onActiveDayChange={setActiveDay}
            highlightedStop={highlightedStop}
            onHighlightStop={setHighlightedStop}
          />
        )}

        <footer className="footer">
          <a href="/docs">{t.footer.api}</a>
          <span aria-hidden="true">·</span>
          <a href={SOURCE_URL} target="_blank" rel="noreferrer">
            {t.footer.source}
          </a>
        </footer>
      </aside>

      <main className={loading ? "map-area loading" : "map-area"}>
        <RouteMap
          cities={cities}
          city={form.city}
          hotel={form.hotel}
          plan={plan}
          activeDay={activeDay}
          highlightedStop={highlightedStop}
          onPickCity={(city) => updateForm({ city, hotel: null })}
          onPickHotel={(hotel) => updateForm({ hotel })}
          onHighlightStop={setHighlightedStop}
          lang={lang}
        />
      </main>
    </div>
  );
}

function errorMessage(error: unknown, lang: Lang): string {
  const e = STRINGS[lang].errors;
  if (!(error instanceof ApiError)) return e.generic;
  if (error.status === 0) return e.network;
  if (error.status === 404) return e.unknownCity;
  if (error.status === 422 && error.message.includes("km from every sight")) return e.tooFar;
  return e.generic;
}
