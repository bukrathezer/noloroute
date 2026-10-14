import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  type City,
  fetchCities,
  fetchGuide,
  fetchMe,
  type Guide,
  getSavedRoute,
  type PlanResponse,
  planRoute,
  removeStop,
  reorderDays,
  saveRoute,
  setAuthToken,
  type TokenResponse,
  updateSavedRoute,
  type User,
} from "./api";
import { AuthPanel } from "./components/AuthPanel";
import { type FormState, PlanForm } from "./components/PlanForm";
import { PlanResult, type SaveState } from "./components/PlanResult";
import { Privacy } from "./components/Privacy";
import { type GuideMap, type Point, RouteMap } from "./components/RouteMap";
import { SavedRoutes } from "./components/SavedRoutes";
import { type GuideFocus, TravelGuide } from "./components/TravelGuide";
import { addDays, firstTripDayIn, fromIso, todayIso } from "./dates";
import { cityName, initialLang, type Lang, STRINGS } from "./i18n";

const SOURCE_URL = "https://github.com/bukrathezer/noloroute";
const AUTH_STORAGE_KEY = "auth";

type View = "plan" | "guide" | "auth" | "saved" | "privacy";
// The two tabs; the other views are screens that go back to the tab they were opened from.
type MainView = "plan" | "guide";

// How close the map comes for the guide: a whole country, or one city.
const GUIDE_COUNTRY_ZOOM = 6;
const GUIDE_CITY_ZOOM = 11;

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
  const [mainView, setMainView] = useState<MainView>("plan");
  const [authReason, setAuthReason] = useState<"save" | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  // Set when the shown plan is a saved route, so edits update it instead of saving a copy.
  const [savedRouteId, setSavedRouteId] = useState<string | null>(null);
  const [removingStop, setRemovingStop] = useState<string | null>(null);
  const [movingDay, setMovingDay] = useState<number | null>(null);
  // The travel guide, by language (fetched once each), and what it shows.
  const [guides, setGuides] = useState<Partial<Record<Lang, Guide>>>({});
  const [guideFailed, setGuideFailed] = useState<Partial<Record<Lang, boolean>>>({});
  const [guideRetry, setGuideRetry] = useState(0);
  const guideLoading = useRef(new Set<Lang>());
  const [guideMonth, setGuideMonth] = useState(() => new Date().getMonth() + 1);
  const [guideCity, setGuideCity] = useState<string | null>(null);
  const [guideFocus, setGuideFocus] = useState<GuideFocus>(null);
  // Ignores responses to requests that were superseded while in flight.
  const requestId = useRef(0);
  const t = STRINGS[lang];

  useEffect(() => {
    fetchCities()
      .then(setCities)
      .catch(() => setCitiesFailed(true));
  }, []);

  // Fetched up front (it's small and cached), so the planner knows which cities have a guide;
  // once per language, and again on a retry after a failure.
  useEffect(() => {
    if (guides[lang] || guideLoading.current.has(lang)) return;
    guideLoading.current.add(lang);
    setGuideFailed((f) => ({ ...f, [lang]: false }));
    fetchGuide(lang)
      .then((g) => setGuides((all) => ({ ...all, [lang]: g })))
      .catch(() => setGuideFailed((f) => ({ ...f, [lang]: true })))
      .finally(() => guideLoading.current.delete(lang));
    // `guides` is read, not watched: a new guide must not start another request.
  }, [lang, guideRetry]);

  const guide = guides[lang] ?? null;

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
    setMainView("plan");
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
    // Saving happens in the planner; otherwise back to the tab the login was opened from.
    showMain(authReason === "save" ? "plan" : mainView);
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
      showMain("plan");
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

  const onMoveDay = async (dayNumber: number, direction: -1 | 1) => {
    if (!plan) return;
    const other = dayNumber + direction;
    const order = plan.days.map((d) => d.day_number);
    [order[dayNumber - 1], order[other - 1]] = [other, dayNumber];
    const id = requestId.current;
    setMovingDay(dayNumber);
    setError(null);
    try {
      const updated = await reorderDays(plan, order);
      if (id !== requestId.current) return; // the form changed meanwhile
      setPlan(updated);
      // A day shown on its own stays in view at its new place.
      setActiveDay((active) => (active === dayNumber ? other : active === other ? dayNumber : active));
      setSaveState(savedRouteId ? "dirty" : "idle");
    } catch {
      if (id === requestId.current) setError(t.result.moveFailed);
    } finally {
      setMovingDay(null);
    }
  };

  function showMain(next: MainView) {
    setMainView(next);
    setView(next);
  }

  /** `month`: show the guide for that month (the planner's trip month), else keep the last one. */
  const openGuide = (cityId: string | null = null, month?: number) => {
    setGuideCity(cityId);
    setGuideFocus(cityId ? { kind: "city", id: cityId } : null);
    if (month) setGuideMonth(month);
    if (guideFailed[lang]) setGuideRetry((n) => n + 1);
    showMain("guide");
  };

  const openGuideCity = (cityId: string | null) => {
    setGuideCity(cityId);
    setGuideFocus(cityId ? { kind: "city", id: cityId } : null);
  };

  // From the guide to the planner: that city, with the trip in that month. What already fits stays
  // (the hotel in the same city, dates already in that month), and so does the plan if nothing changes.
  const planFromGuide = (city: City, month: number) => {
    const patch: Partial<FormState> = {};
    if (form.city?.id !== city.id) Object.assign(patch, { city, hotel: null, hotelLabel: null });
    const datesFit =
      form.startDate !== "" && form.startDate >= todayIso() && fromIso(form.startDate).getMonth() + 1 === month;
    if (!datesFit) patch.startDate = firstTripDayIn(month);
    if (Object.keys(patch).length > 0) updateForm(patch);
    showMain("plan");
  };

  const guideMap = useMemo<GuideMap | null>(() => {
    if (view !== "guide") return null;
    const point = (id: string): Point | null => {
      const c = cities.find((city) => city.id === id);
      return c && c.center_lat != null && c.center_lng != null ? [c.center_lat, c.center_lng] : null;
    };
    // The picks are the same in every language: while a newly chosen language loads, the map
    // keeps showing them from the other one instead of jumping away.
    const shown = guide ?? guides.tr ?? guides.en;
    const picks = shown?.best[guideMonth - 1]?.picks.map((p) => p.city_id) ?? [];
    let focus: GuideMap["focus"] = null;
    if (guideFocus?.kind === "city") {
      const p = point(guideFocus.id);
      focus = p ? { points: [p], maxZoom: GUIDE_CITY_ZOOM } : null;
    } else if (guideFocus?.kind === "country") {
      const ids = cities.filter((c) => c.country_code === guideFocus.code).map((c) => c.id);
      focus = { points: ids.map(point).filter((p): p is Point => p !== null), maxZoom: GUIDE_COUNTRY_ZOOM };
    } else {
      // The month's best places, wherever they are.
      focus = { points: picks.map(point).filter((p): p is Point => p !== null), maxZoom: GUIDE_COUNTRY_ZOOM };
    }
    return {
      highlighted: new Set(picks),
      selected: guideCity,
      focus,
      onPickCity: (city) => openGuideCity(city.id),
    };
  }, [view, cities, guide, guides, guideMonth, guideCity, guideFocus]);

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
            onBack={() => setView(mainView)}
          />
        )}

        {view === "saved" && auth && (
          <SavedRoutes
            lang={lang}
            email={auth.user.email}
            cities={cities}
            onOpen={openSavedRoute}
            onBack={() => showMain("plan")}
            onLogout={logout}
            onUnauthorized={logout}
          />
        )}

        {view === "privacy" && <Privacy lang={lang} onBack={() => setView(mainView)} />}

        {(view === "plan" || view === "guide") && (
          <div className="segmented view-tabs" role="tablist">
            {(["plan", "guide"] as const).map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={view === v}
                className={view === v ? "selected" : undefined}
                onClick={() => (v === "guide" ? openGuide(guideCity) : showMain("plan"))}
              >
                {t.views[v]}
              </button>
            ))}
          </div>
        )}

        {view === "guide" && (
          <TravelGuide
            guide={guide}
            failed={Boolean(guideFailed[lang]) && !guide}
            cities={cities}
            citiesFailed={citiesFailed}
            lang={lang}
            month={guideMonth}
            onMonthChange={(m) => {
              setGuideMonth(m);
              if (!guideCity) setGuideFocus(null);
            }}
            cityId={guideCity}
            onOpenCity={openGuideCity}
            onFocus={setGuideFocus}
            onPlan={planFromGuide}
          />
        )}

        {/* Kept mounted while another view is open, so the plan's loaded suggestions, events
            and half-typed searches are still there on the way back. */}
        <div className="plan-view" hidden={view !== "plan"}>
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
              onShowGuide={
                form.city && guide?.cities.some((c) => c.id === form.city?.id)
                  ? () =>
                      openGuide(
                        form.city?.id ?? null,
                        form.startDate ? fromIso(form.startDate).getMonth() + 1 : undefined,
                      )
                  : undefined
              }
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
                onMoveDay={onMoveDay}
                movingDay={movingDay}
              />
            )}
        </div>

        <footer className="footer">
          <a href="/docs">{t.footer.api}</a>
          <span aria-hidden="true">·</span>
          <a href={SOURCE_URL} target="_blank" rel="noreferrer">
            {t.footer.source}
          </a>
          <span aria-hidden="true">·</span>
          <button type="button" className="link-button footer-link" onClick={() => setView("privacy")}>
            {t.footer.privacy}
          </button>
        </footer>
      </aside>

      <main className={loading && view === "plan" ? "map-area loading" : "map-area"}>
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
          guide={guideMap}
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
