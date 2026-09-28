import { useEffect, useState } from "react";
import { ApiError, type City, deleteSavedRoute, listSavedRoutes, type SavedRouteSummary } from "../api";
import { cityName, type Lang, STRINGS } from "../i18n";

interface Props {
  lang: Lang;
  email: string;
  cities: City[];
  onOpen: (id: string) => void;
  onBack: () => void;
  onLogout: () => void;
  onUnauthorized: () => void;
}

export function SavedRoutes({ lang, email, cities, onOpen, onBack, onLogout, onUnauthorized }: Props) {
  const t = STRINGS[lang];
  const [routes, setRoutes] = useState<SavedRouteSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    listSavedRoutes()
      .then(setRoutes)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) onUnauthorized();
        else setFailed(true);
      });
  }, [onUnauthorized]);

  const remove = async (route: SavedRouteSummary) => {
    if (!window.confirm(t.saved.confirmDelete(route.name))) return;
    try {
      await deleteSavedRoute(route.id);
      setRoutes((list) => list?.filter((r) => r.id !== route.id) ?? null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized();
      else setFailed(true);
    }
  };

  const cityLabel = (id: string) => {
    const city = cities.find((c) => c.id === id);
    return city ? cityName(city, lang) : id;
  };

  return (
    <section className="saved-routes">
      <button type="button" className="link-button back" onClick={onBack}>
        {t.saved.back}
      </button>
      <h2>{t.saved.title}</h2>
      <p className="hint account-line">
        {t.account.signedInAs(email)} ·{" "}
        <button type="button" className="link-button inline" onClick={onLogout}>
          {t.account.logout}
        </button>
      </p>

      {failed && (
        <p className="error" role="alert">
          {t.saved.loadError}
        </p>
      )}
      {!routes && !failed && <p className="hint">{t.saved.loading}</p>}
      {routes?.length === 0 && <p className="empty-state">{t.saved.empty}</p>}

      {routes && routes.length > 0 && (
        <ul className="saved-list">
          {routes.map((route) => (
            <li key={route.id}>
              <button type="button" className="saved-open" onClick={() => onOpen(route.id)}>
                <span className="stop-name">{route.name}</span>
                <span className="muted">
                  {cityLabel(route.city_id)} · {t.saved.meta(route.duration_days, route.stop_count)} ·{" "}
                  {t.mode[route.travel_mode]}
                </span>
                <span className="muted small">
                  {new Date(route.created_at).toLocaleDateString(lang, { dateStyle: "medium" })}
                </span>
              </button>
              <button type="button" className="link-button danger" onClick={() => remove(route)}>
                {t.saved.delete}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
