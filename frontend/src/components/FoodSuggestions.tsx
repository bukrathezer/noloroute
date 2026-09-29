import { useState } from "react";
import { ApiError, type DayPlan, type FoodGroup, foodSuggestions } from "../api";
import { type Lang, STRINGS } from "../i18n";

interface Props {
  day: DayPlan;
  currencyCode: string;
  lang: Lang;
}

type State = { status: "closed" } | { status: "loading" } | { status: "error"; message: string } | { status: "open"; groups: FoodGroup[] };

function openText(hours: string | null, lang: Lang): string | null {
  const r = STRINGS[lang].result;
  if (!hours || hours === "closed") return null;
  return hours === "24/7" ? r.open247 : r.openHours(hours);
}

/** Places to eat near a day's route, loaded only when asked for (each lookup is a paid Google search). */
export function FoodSuggestions({ day, currencyCode, lang }: Props) {
  const t = STRINGS[lang].food;
  const [state, setState] = useState<State>({ status: "closed" });
  const [groups, setGroups] = useState<FoodGroup[] | null>(null);

  if (day.stops.length === 0) return null;

  const toggle = async () => {
    if (state.status === "open") {
      setState({ status: "closed" });
      return;
    }
    if (groups) {
      setState({ status: "open", groups }); // already loaded for this day
      return;
    }
    setState({ status: "loading" });
    try {
      const stops = day.stops.map((s) => ({ name: s.name, lat: s.latitude, lng: s.longitude }));
      const result = await foodSuggestions(stops, day.date, lang);
      setGroups(result);
      setState({ status: "open", groups: result });
    } catch (e) {
      setState({ status: "error", message: e instanceof ApiError && e.status === 429 ? t.tooMany : t.error });
    }
  };

  const symbol =
    new Intl.NumberFormat(lang, { style: "currency", currency: currencyCode })
      .formatToParts(0)
      .find((p) => p.type === "currency")?.value ?? "$";

  return (
    <div className="food">
      <button
        type="button"
        className="link-button food-toggle"
        aria-expanded={state.status === "open"}
        disabled={state.status === "loading"}
        onClick={toggle}
      >
        <span aria-hidden="true">🍽️ </span>
        {state.status === "loading" ? t.loading : state.status === "open" ? t.hide : t.show}
      </button>
      {state.status === "error" && (
        <p className="hint" role="alert">
          {state.message}
        </p>
      )}
      {state.status === "open" && (
        <div className="food-list">
          {state.groups.length === 0 && <p className="hint">{t.empty}</p>}
          {state.groups.map((group) => (
            <div key={group.near} className="food-group">
              <p className="food-near">{t.near(group.near)}</p>
              <ul>
                {group.places.map((place) => (
                  <li key={place.place_id}>
                    {place.maps_url ? (
                      <a href={place.maps_url} target="_blank" rel="noreferrer" className="food-name">
                        {place.name}
                      </a>
                    ) : (
                      <span className="food-name">{place.name}</span>
                    )}
                    <span className="muted small">
                      {[
                        place.cuisine,
                        `★ ${place.rating.toFixed(1)} (${place.rating_count.toLocaleString(lang)})`,
                        place.price_level ? symbol.repeat(place.price_level) : null,
                        openText(place.hours, lang),
                        t.distance(place.distance_m),
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <p className="hint small">{t.note}</p>
        </div>
      )}
    </div>
  );
}
