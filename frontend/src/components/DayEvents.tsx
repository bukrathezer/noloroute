import { useState } from "react";
import { ApiError, type DayPlan, type EventItem, eventSuggestions, type LatLng } from "../api";
import { type Lang, STRINGS } from "../i18n";

interface Props {
  day: DayPlan & { date: string };
  accommodation: LatLng;
  lang: Lang;
}

type State =
  | { status: "closed" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "open"; events: EventItem[] };

function priceText(e: EventItem, lang: Lang): string | null {
  if (e.price_min == null || !e.currency) return null;
  const money = (v: number) =>
    v.toLocaleString(lang, { style: "currency", currency: e.currency ?? "EUR", maximumFractionDigits: 0 });
  return e.price_max != null && e.price_max > e.price_min ? `${money(e.price_min)}–${money(e.price_max)}` : money(e.price_min);
}

/** "14:30, 19:30", or the first three and how many more: some shows run every half hour. */
function timesText(times: string[]): string | null {
  if (times.length === 0) return null;
  const shown = times.slice(0, 3).join(", ");
  return times.length > 3 ? `${shown} +${times.length - 3}` : shown;
}

/** Events starting that day near the accommodation (Ticketmaster), loaded only when asked for. */
export function DayEvents({ day, accommodation, lang }: Props) {
  const s = STRINGS[lang].suggestions;
  const t = STRINGS[lang].events;
  const [state, setState] = useState<State>({ status: "closed" });
  const [loaded, setLoaded] = useState<EventItem[] | null>(null);

  const toggle = async () => {
    if (state.status === "open") {
      setState({ status: "closed" });
      return;
    }
    if (loaded) {
      setState({ status: "open", events: loaded });
      return;
    }
    setState({ status: "loading" });
    try {
      const events = await eventSuggestions(accommodation, day.date, lang);
      setLoaded(events);
      setState({ status: "open", events });
    } catch (e) {
      const unavailable = e instanceof ApiError && e.status === 503;
      setState({
        status: "error",
        message: e instanceof ApiError && e.status === 429 ? s.tooMany : unavailable ? t.unavailable : s.error,
      });
    }
  };

  return (
    <div className="suggestion-block">
      <button
        type="button"
        className="link-button suggestion-toggle"
        aria-expanded={state.status === "open"}
        disabled={state.status === "loading"}
        onClick={toggle}
      >
        <span aria-hidden="true">🎟️ </span>
        {state.status === "loading" ? t.loading : state.status === "open" ? t.hide : t.show}
      </button>
      {state.status === "error" && (
        <p className="hint" role="alert">
          {state.message}
        </p>
      )}
      {state.status === "open" && (
        <div className="suggestion-list">
          {state.events.length === 0 ? (
            <p className="hint">{t.empty}</p>
          ) : (
            <ul>
              {state.events.map((e) => (
                <li key={`${e.name}|${e.venue}`}>
                  {e.url ? (
                    <a href={e.url} target="_blank" rel="noreferrer" className="suggestion-name">
                      {e.name}
                    </a>
                  ) : (
                    <span className="suggestion-name">{e.name}</span>
                  )}
                  <span className="muted small">
                    {[
                      [e.segment && (t.segments[e.segment] ?? e.segment), e.genre].filter(Boolean).join(" · "),
                      timesText(e.times),
                      e.venue,
                      e.distance_km != null ? t.distance(e.distance_km.toLocaleString(lang)) : null,
                      priceText(e, lang),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="hint small">{t.note}</p>
        </div>
      )}
    </div>
  );
}
