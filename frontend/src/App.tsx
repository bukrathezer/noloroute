import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  type City,
  fetchCities,
  fetchMe,
  getSavedRoute,
  type PlanResponse,
  planRoute,
  removeStop,
  saveRoute,
  setAuthToken,
  type TokenResponse,
  updateSavedRoute,
  type User,
} from "./api";
import { AuthPanel } from "./components/AuthPanel";
import { type FormState, PlanForm } from "./components/PlanForm";
import { PlanResult, type SaveState } from "./components/PlanResult";
import { RouteMap } from "./components/RouteMap";
import { SavedRoutes } from "./components/SavedRoutes";
import { addDays, todayIso } from "./dates";
import { cityName, initialLang, type Lang, STRINGS } from "./i18n";

const SOURCE_URL = "https://github.com/bukrathezer/noloroute";
const AUTH_STORAGE_KEY = "auth";

type View = "plan" | "auth" | "saved";

interface Auth {
  token: string;
  user: User;
}

function loadAuth(): Auth | null {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Auth) : null;
  } catch {
    return null;
  }
}

function storeAuth(auth: Auth | null) {
  try {
    if (auth) localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth));
    else localStorage.removeItem(AUTH_STORAGE_KEY);
  } catch {
    // Storage unavailable: the login just won't survive a page reload.
  }
}

export function App() {
  const [lang, setLang] = useState<Lang>(initialLang);
  const [cities, setCities] = useState<City[]>([]);
  const [citiesFailed, setCitiesFailed] = useState(false);
  const [form, setForm] = useState<FormState>({
    city: null,
    hotel: null,
    hotelLabel: null,
    days: 2,
    mode: "WALK",
    budget: "",
    startDate: addDays(todayIso(), 1), // tomorrow: close enough for a real forecast
  });
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeDay, setActiveDay] = useState<number | null>(null);
  const [highlightedStop, setHighlightedStop] = useState<string | null>(null);
  const [auth, setAuth] = useState<Auth | null>(() => {
    const stored = loadAuth();
    setAuthToken(stored?.token ?? null);
    return stored;
  });
  const [view, setView] = useState<View>("plan");
  const [authReason, setAuthReason] = useState<"save" | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  // Set when the shown plan is a saved route, so edits update it instead of saving a copy.
  const [savedRouteId, setSavedRouteId] = useState<string | null>(null);
  const [removingStop, setRemovingStop] = useState<string | null>(null);
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

  const logout = useCallback(() => {
    setAuthToken(null);
    storeAuth(null);
    setAuth(null);
    setView("plan");
    setSaveState("idle");
    setSavedRouteId(null);
  }, []);

  // A stored token may have expired while the tab was closed: check it once on load.
  useEffect(() => {
    if (!auth) return;
    fetchMe().catch((e) => {
      if (e instanceof ApiError && e.status === 401) logout();
    });
    // Only on first load; later logins are fresh.
  }, []);

  const updateForm = (patch: Partial<FormState>) => {
    setForm((f) => ({ ...f, ...patch }));
    // Any change makes the current plan stale.
    requestId.current++;
    setPlan(null);
    setError(null);
    setActiveDay(null);
    setLoading(false);
    setSaveState("idle");
    setSavedRouteId(null);
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
        start_date: form.startDate || undefined,
      });
      if (id !== requestId.current) return;
      setPlan(result);
      setActiveDay(null);
      setSaveState("idle");
      setSavedRouteId(null);
    } catch (e) {
      if (id !== requestId.current) return;
      setError(errorMessage(e, lang));
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  };

  const save = async (planToSave: PlanResponse) => {
    const city = cities.find((c) => c.id === planToSave.city_id);
    const name = t.save.defaultName(city ? cityName(city, lang) : planToSave.city_id, planToSave.duration_days);
    setSaveState("saving");
    try {
      const saved = savedRouteId
        ? await updateSavedRoute(savedRouteId, planToSave)
        : await saveRoute(planToSave, name);
      setSavedRouteId(saved.id);
      setSaveState("saved");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        logout();
        setAuthReason("save");
        setView("auth");
      } else {
        setSaveState("error");
      }
    }
  };

  const requestSave = () => {
    if (!plan) return;
    if (auth) {
      save(plan);
    } else {
      setAuthReason("save");
      setView("auth");
    }
  };

  const onAuthenticated = (result: TokenResponse) => {
    const next = { token: result.access_token, user: result.user };
    setAuthToken(next.token);
    storeAuth(next);
    setAuth(next);
    setView("plan");
    // Finish what the user was doing when they were asked to log in.
    if (authReason === "save" && plan) save(plan);
    setAuthReason(null);
  };

  const openSavedRoute = async (id: string) => {
    try {
      const saved = await getSavedRoute(id);
      const city = cities.find((c) => c.id === saved.plan.city_id) ?? null;
      requestId.current++;
      setForm({
        city,
        hotel: saved.plan.accommodation,
        hotelLabel: null,
        days: saved.plan.duration_days,
        mode: saved.plan.travel_mode,
        budget: saved.plan.budget ?? "",
        startDate: saved.plan.start_date ?? "",
      });
      setPlan(saved.plan);
      setActiveDay(null);
      setError(null);
      setLoading(false);
      setSaveState("saved");
      setSavedRouteId(saved.id);
      setView("plan");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) logout();
      else setError(errorMessage(e, lang));
    }
  };

  const onRemoveStop = async (poiId: string) => {
    if (!plan) return;
    const id = requestId.current;
    setRemovingStop(poiId);
    setError(null);
    try {
      const updated = await removeStop(plan, poiId);
      if (id !== requestId.current) return; // the form changed meanwhile
      setPlan(updated);
      setHighlightedStop(null);
      // A saved route now differs from what is stored; an unsaved plan just stays unsaved.
      setSaveState(savedRouteId ? "dirty" : "idle");
    } catch {
      if (id === requestId.current) setError(t.result.removeFailed);
    } finally {
      setRemovingStop(null);
    }
  };

  const showAuth = () => {
    setAuthReason(null);
    setView("auth");
  };

  return (
    <div className="app">
      <aside className="panel">
        <header className="brand">
          <a className="logo" href="/">
            <img src="/favicon.svg" alt="" width={28} height={28} />
            <span>NoloRoute</span>
          </a>
          <div className="header-actions">
            {auth ? (
              <button type="button" className="pill-button" onClick={() => setView("saved")}>
                {t.account.myRoutes}
              </button>
            ) : (
              <button type="button" className="pill-button" onClick={showAuth}>
                {t.account.login}
              </button>
            )}
            <button type="button" className="pill-button" onClick={() => setLang(lang === "tr" ? "en" : "tr")}>
              {t.switchLanguage}
            </button>
          </div>
        </header>

        {view === "auth" && (
          <AuthPanel
            lang={lang}
            reason={authReason}
            onAuthenticated={onAuthenticated}
            onBack={() => setView("plan")}
          />
        )}

        {view === "saved" && auth && (
          <SavedRoutes
            lang={lang}
            email={auth.user.email}
            cities={cities}
            onOpen={openSavedRoute}
            onBack={() => setView("plan")}
            onLogout={logout}
            onUnauthorized={logout}
          />
        )}

        {view === "plan" && (
          <>
            <p className="tagline">{t.tagline}</p>

            {citiesFailed && (
              <p className="error" role="alert">
                {t.errors.loadCities}
              </p>
            )}

            <PlanForm
              cities={cities}
              form={form}
              onChange={updateForm}
              onSubmit={submit}
              loading={loading}
              lang={lang}
            />

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
                saveState={saveState}
                onSave={requestSave}
                onShowSaved={() => setView("saved")}
                onRemoveStop={onRemoveStop}
                removingStop={removingStop}
              />
            )}
          </>
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
          onPickCity={(city) => updateForm({ city, hotel: null, hotelLabel: null })}
          onPickHotel={(hotel) => updateForm({ hotel, hotelLabel: null })}
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
  if (error.status === 429) return e.tooMany;
  if (error.status === 422 && error.message.includes("km from every sight")) return e.tooFar;
  return e.generic;
}
