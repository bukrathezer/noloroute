import { useState } from "react";
import {
  ApiError,
  type DayPlan,
  foodSuggestions,
  type LatLng,
  nightlifeSuggestions,
  type SuggestionGroup,
} from "../api";
import { type Lang, STRINGS } from "../i18n";

export type SuggestionKind = "food" | "nightlife";

interface Props {
  kind: SuggestionKind;
  day: DayPlan;
  accommodation: LatLng;
  currencyCode: string;
  lang: Lang;
}

type State =
  | { status: "closed" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "open"; groups: SuggestionGroup[] };

const ICONS: Record<SuggestionKind, string> = { food: "🍽️", nightlife: "🌙" };

function openText(hours: string | null, lang: Lang): string | null {
  const r = STRINGS[lang].result;
  if (!hours || hours === "closed") return null;
  return hours === "24/7" ? r.open247 : r.openHours(hours);
}

/** Places to eat along a day's route, or to go out near where it ends: loaded only when asked
 * for, as each lookup is a paid Google search. */
export function Suggestions({ kind, day, accommodation, currencyCode, lang }: Props) {
  const s = STRINGS[lang].suggestions;
  const t = s[kind];
  const [state, setState] = useState<State>({ status: "closed" });
  const [loaded, setLoaded] = useState<SuggestionGroup[] | null>(null);

  const toggle = async () => {
    if (state.status === "open") {
      setState({ status: "closed" });
      return;
    }
    if (loaded) {
      setState({ status: "open", groups: loaded }); // already fetched for this day
      return;
    }
    setState({ status: "loading" });
    try {
      const stops = day.stops.map((stop) => ({ name: stop.name, lat: stop.latitude, lng: stop.longitude }));
      const groups =
        kind === "food"
          ? await foodSuggestions(stops, day.date, lang)
          : await nightlifeSuggestions(accommodation, stops, day.date, lang);
      setLoaded(groups);
      setState({ status: "open", groups });
    } catch (e) {
      setState({ status: "error", message: e instanceof ApiError && e.status === 429 ? s.tooMany : s.error });
    }
  };

  const symbol =
    new Intl.NumberFormat(lang, { style: "currency", currency: currencyCode })
      .formatToParts(0)
      .find((p) => p.type === "currency")?.value ?? "$";

  return (
    <div className="suggestion-block">
      <button
        type="button"
        className="link-button suggestion-toggle"
        aria-expanded={state.status === "open"}
        disabled={state.status === "loading"}
        onClick={toggle}
      >
        <span aria-hidden="true">{ICONS[kind]} </span>
        {state.status === "loading" ? t.loading : state.status === "open" ? t.hide : t.show}
      </button>
      {state.status === "error" && (
        <p className="hint" role="alert">
          {state.message}
        </p>
      )}
      {state.status === "open" && (
        <div className="suggestion-list">
          {state.groups.length === 0 && <p className="hint">{t.empty}</p>}
          {state.groups.map((group) => (
            <div key={group.near ?? "hotel"}>
              <p className="suggestion-near">{group.near === null ? s.nearHotel : s.near(group.near)}</p>
              <ul>
                {group.places.map((place) => (
                  <li key={place.place_id}>
                    {place.maps_url ? (
                      <a href={place.maps_url} target="_blank" rel="noreferrer" className="suggestion-name">
                        {place.name}
                      </a>
                    ) : (
                      <span className="suggestion-name">{place.name}</span>
                    )}
                    <span className="muted small">
                      {[
                        place.category,
                        `★ ${place.rating.toFixed(1)} (${place.rating_count.toLocaleString(lang)})`,
                        place.price_level ? symbol.repeat(place.price_level) : null,
                        openText(place.hours, lang),
                        s.distance(place.distance_m),
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <p className="hint small">{s.note}</p>
        </div>
      )}
    </div>
  );
}
