import {
  Component,
  lazy,
  type ReactNode,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ApiError,
  type City,
  fetchCities,
  fetchGuide,
  fetchMe,
  type Guide,
  getSavedRoute,
  getSharedPlan,
  type PlanResponse,
  planRoute,
  removeStop,
  reorderDays,
  saveRoute,
  setAuthToken,
  type SharedPlan,
  sharePlan,
  type TokenResponse,
  updateSavedRoute,
  type User,
} from "./api";
import { type AuthMode, AuthPanel } from "./components/AuthPanel";
import { HALF_SHARE, PEEK_HEIGHT, SheetHandle, type SheetState } from "./components/BottomSheet";
import { type FormState, PlanForm } from "./components/PlanForm";
import { PlanResult } from "./components/PlanResult";
import { Privacy } from "./components/Privacy";
import { type GuideMap, type Point, RouteMap } from "./components/RouteMap";
import { SavedRoutes } from "./components/SavedRoutes";
import { AdminPanel } from "./components/AdminPanel";
import { ShareInvite } from "./components/ShareInvite";
import { type Section, TopBar } from "./components/TopBar";
import { type GuideFocus, TravelGuide } from "./components/TravelGuide";
import { type SaveState, type ShareState, TripSummary } from "./components/TripSummary";
import { Icon } from "./components/Icon";
import { addDays, firstTripDayIn, fromIso, todayIso } from "./dates";
import { cityName, initialLang, type Lang, STRINGS } from "./i18n";
import { canAddToHomeScreen, useInstallPrompt } from "./install";

// Only first visits see it: loaded on demand, globe and all.
const Welcome = lazy(() => import("./components/Welcome"));

// If the welcome screen can't load (a network blip, a deploy since the page loaded), go on to the app.
class SkipOnError extends Component<{ onError: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onError();
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

const AUTH_STORAGE_KEY = "auth";
const WELCOME_SEEN_KEY = "welcomeSeen";
const INVITE_CLOSED_KEY = "shareInviteClosed";
// How long someone looks at a shared plan before it invites them to sign up.
const INVITE_DELAY_MS = 4000;
// A shared plan's link (app/api/v1/routes_share.py).
const SHARE_PATH = /^\/p\/([A-Za-z0-9]{8})$/;
// The privacy note's own address (Google's sign-in screen links to it).
const PRIVACY_PATH = /^\/(gizlilik|privacy)\/?$/;

type View = "plan" | "guide" | "auth" | "saved" | "admin" | "privacy";
// The two tabs; the other views are screens that go back to the tab they were opened from.
type MainView = "plan" | "guide";

// How close the map comes for the guide: a whole country, or one city.
const GUIDE_COUNTRY_ZOOM = 6;
const GUIDE_CITY_ZOOM = 11;

// The phone layout of styles.css: the map fills the screen, the panel is a sheet pulled up over
// it, the menu sits at the bottom. What covers the map there, in px, so routes are framed clear of it.
const PHONE_QUERY = "(max-width: 860px)";
const PHONE_TOP_BAR = 72;
const PHONE_MENU = 64;

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const list = window.matchMedia?.(query);
    if (!list) return;
    const update = () => setMatches(list.matches);
    update();
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);
  return matches;
}

interface Auth {
  token: string;
  user: User;
  /** "Remember me": kept in localStorage; else in sessionStorage, gone when the browser closes. */
  remember: boolean;
}

// The plan of the link the page was opened with (/p/<id>): loading, not there, or shown until it
// changes. Dropped once the user does something else. The address bar keeps the link while it
// loads, is shown, or failed to load (a reload tries again).
type SharedLink =
  | { id: string; status: "loading" | "missing" | "failed" }
  | { id: string; status: "shown"; plan: PlanResponse };

function linkOfPage(): SharedLink | null {
  const id = SHARE_PATH.exec(window.location.pathname)?.[1];
  return id ? { id, status: "loading" } : null;
}

function leaveSharedLink() {
  window.history.replaceState(null, "", "/");
  document.title = "NoloRoute"; // the link's page came with the plan's title
}

function loadAuth(): Auth | null {
  try {
    for (const remember of [true, false]) {
      const raw = (remember ? localStorage : sessionStorage).getItem(AUTH_STORAGE_KEY);
      if (raw) return { ...(JSON.parse(raw) as Auth), remember };
    }
  } catch {
    // Storage unavailable or unreadable: logged out.
  }
  return null;
}

function readFlag(key: string): boolean {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function setFlag(key: string) {
  try {
    localStorage.setItem(key, "1");
  } catch {
    // Storage unavailable: it just shows again next time.
  }
}

function storeAuth(auth: Auth | null) {
  try {
    localStorage.removeItem(AUTH_STORAGE_KEY);
    sessionStorage.removeItem(AUTH_STORAGE_KEY);
    if (auth) (auth.remember ? localStorage : sessionStorage).setItem(AUTH_STORAGE_KEY, JSON.stringify(auth));
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
    startDate: addDays(todayIso(), 1), // tomorrow: close enough for a real forecast
  });
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  // The form shown again over a plan, to change the trip ("Edit"); a plan otherwise hides it.
  const [editing, setEditing] = useState(false);
  const phone = useMediaQuery(PHONE_QUERY);
  const [sheet, setSheet] = useState<SheetState>("half");
  const panelRef = useRef<HTMLElement>(null);
  // Counts the plans shown (planned, opened), not their edits: each new one starts at the panel's top.
  const [plansShown, setPlansShown] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeDay, setActiveDay] = useState<number | null>(null);
  const [highlightedStop, setHighlightedStop] = useState<string | null>(null);
  const [auth, setAuth] = useState<Auth | null>(() => {
    const stored = loadAuth();
    setAuthToken(stored?.token ?? null);
    return stored;
  });
  const [view, setView] = useState<View>(() => (PRIVACY_PATH.test(window.location.pathname) ? "privacy" : "plan"));
  const [mainView, setMainView] = useState<MainView>("plan");
  const [authReason, setAuthReason] = useState<"save" | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  // The welcome screen, for a first visit: not after logging in, nor for someone opening a shared plan.
  const [showWelcome, setShowWelcome] = useState(
    () => !auth && !linkOfPage() && !PRIVACY_PATH.test(window.location.pathname) && !readFlag(WELCOME_SEEN_KEY),
  );
  const [inviteReady, setInviteReady] = useState(false);
  const [inviteClosed, setInviteClosed] = useState(() => readFlag(INVITE_CLOSED_KEY));
  // Leaving the welcome screen puts the keyboard focus on the app, not lost on the page.
  const logo = useRef<HTMLAnchorElement>(null);
  const focusAppNext = useRef(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  // Set when the shown plan is a saved route, so edits update it instead of saving a copy.
  const [savedRouteId, setSavedRouteId] = useState<string | null>(null);
  const [removingStop, setRemovingStop] = useState<string | null>(null);
  const [movingDay, setMovingDay] = useState<number | null>(null);
  const [sharedLink, setSharedLink] = useState<SharedLink | null>(linkOfPage);
  // Waits here until the city list is there to fill in the form.
  const [openedShare, setOpenedShare] = useState<SharedPlan | null>(null);
  // Sharing the plan shown: forgotten once the plan changes.
  const [share, setShare] = useState<{ plan: PlanResponse; state: ShareState } | null>(null);
  const { canInstall, install } = useInstallPrompt();
  const [showIosInstall, setShowIosInstall] = useState(false);
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
    if (sharedLink?.status !== "loading") return;
    const { id } = sharedLink;
    let ignore = false;
    getSharedPlan(id)
      .then((opened) => {
        if (!ignore) setOpenedShare(opened);
      })
      .catch((e) => {
        if (ignore) return;
        const status = e instanceof ApiError && e.status === 404 ? "missing" : "failed";
        setSharedLink((link) => (link?.id === id && link.status === "loading" ? { id, status } : link));
      });
    return () => {
      ignore = true;
    };
    // Only for the link the page was opened with.
  }, []);

  // Shown once the city list is there to fill in the form, unless the user started something else.
  useEffect(() => {
    if (!openedShare || (cities.length === 0 && !citiesFailed)) return;
    setOpenedShare(null);
    if (sharedLink?.status !== "loading" || sharedLink.id !== openedShare.id) return;
    showStoredPlan(openedShare.plan, null, false);
    setSharedLink({ id: openedShare.id, status: "shown", plan: openedShare.plan });
  }, [openedShare, cities, citiesFailed]);

  useEffect(() => {
    if (!showWelcome && focusAppNext.current) {
      focusAppNext.current = false;
      logo.current?.focus();
    }
  }, [showWelcome]);

  // Someone looking at a shared plan for a few seconds gets a small invitation to sign up.
  const sharedPlanShown = sharedLink?.status === "shown" && sharedLink.plan === plan;
  useEffect(() => {
    if (!sharedPlanShown) return;
    const timer = setTimeout(() => setInviteReady(true), INVITE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [sharedPlanShown]);

  // Another plan (edited, planned, a saved one opened): the link has nothing more to say.
  useEffect(() => {
    if (!sharedLink) return;
    if (sharedLink.status === "shown" ? plan !== sharedLink.plan : plan !== null) setSharedLink(null);
  }, [plan, sharedLink]);

  useEffect(() => {
    if ((sharedLink === null || sharedLink.status === "missing") && SHARE_PATH.test(window.location.pathname)) {
      leaveSharedLink();
    }
  }, [sharedLink]);

  // On a phone the planner opens half way up over the map; the other screens take the whole sheet.
  useEffect(() => {
    setSheet(view === "plan" ? "half" : "full");
  }, [view]);

  // A new plan, or the form brought back over it, is read from the top.
  useEffect(() => {
    panelRef.current?.scrollTo({ top: 0 });
  }, [plansShown, editing]);

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

  // A stored token may have expired while the tab was closed: check it once on load, and bring
  // the account details up to date (whether it has a password, say).
  useEffect(() => {
    if (!auth) return;
    const checked = auth.token; // a later login (another account, say) mustn't take this answer
    fetchMe()
      .then((user) =>
        setAuth((current) => {
          if (!current || current.token !== checked) return current;
          const next = { ...current, user };
          storeAuth(next);
          return next;
        }),
      )
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401 && loadAuth()?.token === checked) logout();
      });
    // Only on first load; later logins are fresh.
  }, []);

  const updateForm = (patch: Partial<FormState>) => {
    setForm((f) => ({ ...f, ...patch }));
    // Any change makes the current plan stale, and the page's link (if any) beside the point.
    requestId.current++;
    setSharedLink(null);
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
      const result = await planRoute({
        city_id: form.city.id,
        accommodation: form.hotel,
        duration_days: form.days,
        travel_mode: form.mode,
        start_date: form.startDate || undefined,
      });
      if (id !== requestId.current) return;
      setPlan(result);
      setEditing(false);
      setSheet("half");
      setPlansShown((n) => n + 1);
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
        setAuthMode("login");
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
      setAuthMode("login");
      setView("auth");
    }
  };

  const onAuthenticated = (result: TokenResponse, remember: boolean) => {
    const next = { token: result.access_token, user: result.user, remember };
    setAuthToken(next.token);
    storeAuth(next);
    setAuth(next);
    // Saving happens in the planner; otherwise back to the tab the login was opened from.
    showMain(authReason === "save" ? "plan" : mainView);
    // Finish what the user was doing when they were asked to log in.
    if (authReason === "save" && plan) save(plan);
    setAuthReason(null);
  };

  // A plan made earlier (a saved route, a shared link), shown as if just planned. The form gets its
  // trip, except a start date already past: planning again from that date would be refused.
  // `open`: switch to the planner (a saved route is opened from My routes).
  function showStoredPlan(stored: PlanResponse, savedId: string | null, open = true) {
    const start = stored.start_date;
    requestId.current++;
    setForm({
      city: cities.find((c) => c.id === stored.city_id) ?? null,
      hotel: stored.accommodation,
      hotelLabel: null,
      days: stored.duration_days,
      mode: stored.travel_mode,
      startDate: start == null ? "" : start >= todayIso() ? start : addDays(todayIso(), 1),
    });
    setPlan(stored);
    setEditing(false);
    setSheet("half");
    setPlansShown((n) => n + 1);
    setActiveDay(null);
    setError(null);
    setLoading(false);
    setSaveState(savedId ? "saved" : "idle");
    setSavedRouteId(savedId);
    if (open) showMain("plan");
  }

  const openSavedRoute = async (id: string) => {
    try {
      const saved = await getSavedRoute(id);
      showStoredPlan(saved.plan, saved.id);
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

  const onShare = async () => {
    if (!plan) return;
    const shown = plan;
    const city = cities.find((c) => c.id === shown.city_id);
    const title = t.share.title(city ? cityName(city, lang) : shown.city_id, shown.duration_days);
    const linkTo = (path: string) => new URL(path, window.location.origin).href;
    // The plan of the page's link already has one.
    if (sharedLink?.status === "shown" && sharedLink.plan === shown) {
      setShare({ plan: shown, state: { status: "done", url: linkTo(`/p/${sharedLink.id}`), title } });
      return;
    }
    setShare({ plan: shown, state: { status: "sharing" } });
    // Unless another plan is being shared by now.
    const settle = (state: ShareState) => setShare((s) => (s?.plan === shown ? { plan: shown, state } : s));
    try {
      const { path } = await sharePlan(shown, lang);
      settle({ status: "done", url: linkTo(path), title });
    } catch {
      settle({ status: "error" });
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

  const showAuth = (mode: AuthMode = "login") => {
    setAuthReason(null);
    setAuthMode(mode);
    setView("auth");
  };

  // The main menu: saved routes need an account, so guests are asked to log in first.
  const navigate = (section: Section) => {
    if (section === "plan") showMain("plan");
    else if (section === "guide") openGuide(guideCity);
    else if (auth) setView("saved");
    else showAuth();
  };
  const section: Section | null =
    view === "plan" || view === "guide"
      ? view
      : view === "saved" || view === "admin"
        ? "saved"
        : view === "auth" && authReason === "save"
          ? "plan"
          : null;

  const leaveWelcome = () => {
    setFlag(WELCOME_SEEN_KEY);
    focusAppNext.current = true;
    setShowWelcome(false);
  };

  if (showWelcome) {
    return (
      <SkipOnError onError={() => setShowWelcome(false)}>
        <Suspense fallback={<div className="welcome" />}>
          <Welcome
          lang={lang}
          onSwitchLanguage={() => setLang(lang === "tr" ? "en" : "tr")}
          cities={cities}
          onAuthenticated={(result, remember) => {
            leaveWelcome();
            onAuthenticated(result, remember);
          }}
          onGuest={leaveWelcome}
          onGuide={() => {
            leaveWelcome();
            openGuide();
          }}
          />
        </Suspense>
      </SkipOnError>
    );
  }

  return (
    <div className="app">
      <TopBar
        lang={lang}
        section={section}
        email={auth?.user.email ?? null}
        logoRef={logo}
        onLogo={(e) => {
          // Guests go back to the welcome screen; the planner keeps what they were doing.
          if (auth) return;
          e.preventDefault();
          setShowWelcome(true);
        }}
        onNavigate={navigate}
        onLogin={() => showAuth()}
        onSwitchLanguage={() => setLang(lang === "tr" ? "en" : "tr")}
      />
      <aside className="panel" ref={panelRef} data-sheet={sheet}>
        {phone && <SheetHandle panel={panelRef} state={sheet} onChange={setSheet} label={t.sheetHandle} />}
        {view === "auth" && (
          <AuthPanel
            key={authMode}
            lang={lang}
            reason={authReason}
            initialMode={authMode}
            onAuthenticated={onAuthenticated}
            onBack={() => setView(mainView)}
          />
        )}

        {view === "saved" && auth && (
          <SavedRoutes
            lang={lang}
            email={auth.user.email}
            hasPassword={auth.user.has_password !== false}
            onShowAdmin={auth.user.is_admin ? () => setView("admin") : undefined}
            cities={cities}
            onOpen={openSavedRoute}
            onBack={() => showMain("plan")}
            onLogout={logout}
            onUnauthorized={logout}
          />
        )}

        {view === "admin" && auth?.user.is_admin && (
          <AdminPanel lang={lang} onBack={() => setView("saved")} onUnauthorized={logout} />
        )}

        {view === "privacy" && (
          <Privacy
            lang={lang}
            onBack={() => {
              if (PRIVACY_PATH.test(window.location.pathname)) window.history.replaceState(null, "", "/");
              setView(mainView);
            }}
          />
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
            {plan && !editing ? (
              <TripSummary
                plan={plan}
                city={cities.find((c) => c.id === plan.city_id) ?? null}
                stayLabel={form.hotelLabel}
                lang={lang}
                saveState={saveState}
                onSave={requestSave}
                onShowSaved={() => setView("saved")}
                shareState={share?.plan === plan ? share.state : null}
                onShare={onShare}
                sharedWithYou={sharedLink?.status === "shown" && sharedLink.plan === plan}
                onEdit={() => setEditing(true)}
              />
            ) : (
              <>
                {plan && (
                  <button type="button" className="link-button back" onClick={() => setEditing(false)}>
                    <Icon name="back" size={16} />
                    {t.summary.backToPlan}
                  </button>
                )}
                <div className="form-intro">
                  <h1>{plan ? t.summary.editTrip : t.summary.newTrip}</h1>
                  <p className="tagline">{t.tagline}</p>
                </div>

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
              </>
            )}

            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}

            {sharedLink?.status === "loading" && <p className="hint">{t.share.loading}</p>}
            {(sharedLink?.status === "missing" || sharedLink?.status === "failed") && (
              <p className="error" role="alert">
                {sharedLink.status === "missing" ? t.share.notFound : t.share.loadError}
              </p>
            )}

            {plan && !editing && (
              <PlanResult
                plan={plan}
                lang={lang}
                activeDay={activeDay}
                onActiveDayChange={setActiveDay}
                highlightedStop={highlightedStop}
                onHighlightStop={setHighlightedStop}
                onRemoveStop={onRemoveStop}
                removingStop={removingStop}
                onMoveDay={onMoveDay}
                movingDay={movingDay}
              />
            )}
        </div>

        <footer className="footer">
          {/* In a new window: inside the installed app it would have no way back. */}
          <button type="button" className="link-button footer-link" onClick={() => setView("privacy")}>
            {t.footer.privacy}
          </button>
          {(canInstall || canAddToHomeScreen()) && (
            <>
              <span aria-hidden="true">·</span>
              <button
                type="button"
                className="link-button footer-link install"
                aria-expanded={canInstall ? undefined : showIosInstall}
                onClick={canInstall ? install : () => setShowIosInstall((shown) => !shown)}
              >
                {t.footer.install}
              </button>
            </>
          )}
        </footer>
        {showIosInstall && <p className="hint small">{t.footer.iosInstall}</p>}
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
          insets={
            phone
              ? {
                  top: PHONE_TOP_BAR,
                  bottom:
                    PHONE_MENU + (sheet === "peek" ? PEEK_HEIGHT : Math.round(window.innerHeight * HALF_SHARE)),
                }
              : null
          }
        />
        {sharedPlanShown && inviteReady && !auth && !inviteClosed && view === "plan" && (
          <ShareInvite
            lang={lang}
            onRegister={() => showAuth("register")}
            onLogin={() => showAuth("login")}
            onClose={() => {
              setFlag(INVITE_CLOSED_KEY);
              setInviteClosed(true);
            }}
          />
        )}
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
