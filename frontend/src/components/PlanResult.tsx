import type { CSSProperties } from "react";
import type { DayWeather, LegDetails, PlanResponse, TravelMode } from "../api";
import { formatDay, formatMonth } from "../dates";
import { type Lang, STRINGS } from "../i18n";
import { dayColor } from "../theme";
import { DayEvents } from "./DayEvents";
import { Suggestions } from "./Suggestions";

// "dirty": a saved route was edited and the changes are not stored yet.
export type SaveState = "idle" | "saving" | "saved" | "dirty" | "error";

interface Props {
  plan: PlanResponse;
  lang: Lang;
  activeDay: number | null;
  onActiveDayChange: (day: number | null) => void;
  highlightedStop: string | null;
  onHighlightStop: (poiId: string | null) => void;
  saveState: SaveState;
  onSave: () => void;
  onShowSaved: () => void;
  onRemoveStop: (poiId: string) => void;
  /** The stop being removed right now, if any. */
  removingStop: string | null;
}

export function PlanResult(props: Props) {
  const { plan, lang, activeDay, onActiveDayChange, highlightedStop, onHighlightStop } = props;
  const { saveState, onSave, onShowSaved, onRemoveStop, removingStop } = props;
  const t = STRINGS[lang];
  const r = t.result;
  const stopCount = plan.days.reduce((n, d) => n + d.stops.length, 0);
  const visit = plan.days.reduce((n, d) => n + d.total_visit_minutes, 0);
  const travel = plan.days.reduce((n, d) => n + d.total_travel_minutes, 0);
  const cost = Number(plan.total_entry_cost);
  const allUnpriced = plan.unpriced_stop_count === stopCount;
  const days = activeDay ? plan.days.filter((d) => d.day_number === activeDay) : plan.days;
  const transit = plan.travel_mode === "TRANSIT";
  const noTransitData = transit && plan.days.some((d) => d.transit_available === false);
  const money = (amount: string) => {
    const value = Number(amount);
    if (value === 0) return r.free;
    return value.toLocaleString(lang, {
      style: "currency",
      currency: plan.currency_code,
      maximumFractionDigits: Number.isInteger(value) ? 0 : 2,
    });
  };

  return (
    <section className="plan-result" aria-live="polite">
      <div className="result-header">
        <h2>{r.summary(stopCount, plan.duration_days)}</h2>
        {saveState === "saved" ? (
          <button type="button" className="saved-badge" onClick={onShowSaved}>
            ✓ {t.save.saved}
          </button>
        ) : (
          <button type="button" className="secondary-button" onClick={onSave} disabled={saveState === "saving"}>
            {saveState === "saving" ? t.save.saving : saveState === "dirty" ? t.save.saveChanges : t.save.button}
          </button>
        )}
      </div>
      {saveState === "error" && (
        <p className="error" role="alert">
          {t.save.error}
        </p>
      )}
      <dl className="stats">
        <div>
          <dt>{r.sightseeing}</dt>
          <dd>{t.minutes(visit)}</dd>
        </div>
        <div>
          <dt>{r.travel}</dt>
          <dd>{t.minutes(travel)}</dd>
        </div>
        <div>
          <dt>{r.entryCost}</dt>
          <dd>
            {allUnpriced
              ? r.unknownCost
              : cost.toLocaleString(lang, { style: "currency", currency: plan.currency_code, maximumFractionDigits: 0 })}
          </dd>
        </div>
      </dl>
      {plan.unpriced_stop_count > 0 && <p className="hint">{r.unpriced(plan.unpriced_stop_count)}</p>}
      {plan.price_basis && plan.prices_checked_on && (
        <p className="hint">{r.priceBasis[plan.price_basis](formatMonth(plan.prices_checked_on, lang))}</p>
      )}
      {transit && <p className="hint">{noTransitData ? r.noTransit : r.mapLegend}</p>}

      {plan.days.length > 1 && (
        <div className="day-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activeDay === null}
            className={activeDay === null ? "selected" : undefined}
            onClick={() => onActiveDayChange(null)}
          >
            {r.allDays}
          </button>
          {plan.days.map((d) => (
            <button
              key={d.day_number}
              type="button"
              role="tab"
              aria-selected={activeDay === d.day_number}
              title={r.focusDay(d.day_number)}
              className={activeDay === d.day_number ? "selected" : undefined}
              style={{ "--day": dayColor(d.day_number) } as CSSProperties}
              onClick={() => onActiveDayChange(d.day_number)}
            >
              <span className="swatch" aria-hidden="true" />
              {r.day(d.day_number)}
            </button>
          ))}
        </div>
      )}

      {days.map((day) => (
        <article
          key={day.day_number}
          className="day-card"
          style={{ "--day": dayColor(day.day_number) } as CSSProperties}
        >
          <header>
            <h3>
              <span className="swatch" aria-hidden="true" />
              {r.day(day.day_number)}
              {day.date && <span className="day-date">{formatDay(day.date, lang)}</span>}
            </h3>
            <span className="muted">
              {r.stopsCount(day.stops.length)} · {t.minutes(day.total_visit_minutes + day.total_travel_minutes)}
            </span>
          </header>
          {day.weather && <WeatherLine weather={day.weather} lang={lang} />}
          {day.rain_adjusted && <p className="hint rain-note">{r.rainNote}</p>}
          {day.dropped_stops && day.dropped_stops.length > 0 && (
            <p className="hint">{r.dropped(day.dropped_stops.join(", "))}</p>
          )}
          {day.routing_source === "estimate" && day.stops.length > 0 && <p className="badge">{r.estimated}</p>}
          {day.stops.length === 0 ? (
            <p className="hint">{r.emptyDay}</p>
          ) : (
            <ol className="stops">
              {day.stops.map((stop) => (
                <li
                  key={stop.poi_id}
                  className={
                    [highlightedStop === stop.poi_id && "highlighted", removingStop === stop.poi_id && "removing"]
                      .filter(Boolean)
                      .join(" ") || undefined
                  }
                  onMouseEnter={() => onHighlightStop(stop.poi_id)}
                  onMouseLeave={() => onHighlightStop(null)}
                >
                  <LegLine
                    mode={plan.travel_mode}
                    details={stop.leg_from_previous}
                    minutes={stop.travel_minutes_from_previous}
                    km={stop.distance_km_from_previous}
                    fromHotel={stop.order_in_day === 1}
                    lang={lang}
                  />
                  <div className="stop-row">
                    <button type="button" className="stop" onClick={() => onHighlightStop(stop.poi_id)}>
                      <span className="stop-number">{stop.order_in_day}</span>
                      <span className="stop-body">
                        <span className="stop-name">{stop.name}</span>
                        <span className="muted">
                          {t.categories[stop.category] ?? stop.category} · {t.minutes(stop.visit_minutes)} {r.visit}
                          {stop.rating != null && ` · ★ ${stop.rating.toFixed(1)}`}
                          {stop.entry_price != null && ` · ${money(stop.entry_price)}`}
                        </span>
                        {stop.hours && stop.hours !== "closed" && (
                          <span className="muted small">
                            {stop.hours === "24/7" ? r.open247 : r.openHours(stop.hours)}
                          </span>
                        )}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="remove-stop"
                      aria-label={r.removeStop(stop.name)}
                      title={r.removeStop(stop.name)}
                      disabled={removingStop !== null}
                      onClick={() => onRemoveStop(stop.poi_id)}
                    >
                      ×
                    </button>
                  </div>
                </li>
              ))}
              <li className="return">
                <LegLine
                  mode={plan.travel_mode}
                  details={day.return_leg}
                  minutes={day.return_travel_minutes}
                  km={day.return_distance_km}
                  fromHotel={false}
                  lang={lang}
                />
                <div className="stop">
                  <span className="stop-number hotel" aria-hidden="true">
                    ⌂
                  </span>
                  <span className="stop-name">{r.backToHotel}</span>
                </div>
              </li>
            </ol>
          )}
          {day.stops.length > 0 && (
            // Keyed by the day's date and stops: a change starts the suggestions afresh.
            <div className="suggestions" key={`${day.date ?? ""}|${day.stops.map((s) => s.poi_id).join(",")}`}>
              {(["food", "nightlife"] as const).map((kind) => (
                <Suggestions
                  key={kind}
                  kind={kind}
                  day={day}
                  accommodation={plan.accommodation}
                  currencyCode={plan.currency_code}
                  lang={lang}
                />
              ))}
              {day.date !== null && (
                <DayEvents day={{ ...day, date: day.date }} accommodation={plan.accommodation} lang={lang} />
              )}
            </div>
          )}
        </article>
      ))}
      {plan.days.some((d) => d.routing_source === "google") && <p className="attribution">{r.attribution}</p>}
    </section>
  );
}

const VEHICLE_ICONS: Record<string, string> = {
  SUBWAY: "🚇",
  METRO_RAIL: "🚇",
  TRAM: "🚊",
  LIGHT_RAIL: "🚊",
  MONORAIL: "🚝",
  BUS: "🚌",
  INTERCITY_BUS: "🚌",
  TROLLEYBUS: "🚎",
  SHARE_TAXI: "🚐",
  FERRY: "⛴️",
  CABLE_CAR: "🚡",
  GONDOLA_LIFT: "🚡",
  FUNICULAR: "🚞",
  RAIL: "🚆",
  HEAVY_RAIL: "🚆",
  COMMUTER_TRAIN: "🚆",
  LONG_DISTANCE_TRAIN: "🚆",
  HIGH_SPEED_TRAIN: "🚄",
};

interface LegLineProps {
  mode: TravelMode;
  /** Set in transit plans: whether this leg is walked or ridden, and on which lines. */
  details: LegDetails | null | undefined;
  minutes: number;
  km: number;
  fromHotel: boolean;
  lang: Lang;
}

/** The travel line above a stop: "Walking 12 min · 0.9 km", plus the rides of a transit leg. */
function LegLine({ mode, details, minutes, km, fromHotel, lang }: LegLineProps) {
  const t = STRINGS[lang];
  const r = t.result;
  const distance = km.toLocaleString(lang, { maximumFractionDigits: 1 });
  const extras: string[] = [];
  if (details?.mode === "TRANSIT" && details.walk_minutes) extras.push(r.walkingPart(t.minutes(details.walk_minutes)));
  if (details?.alternative_mode && details.alternative_minutes != null) {
    extras.push(r.alternative[details.alternative_mode](t.minutes(details.alternative_minutes)));
  }

  return (
    <div className="leg">
      <span>
        {details?.mode === "WALK" && <span aria-hidden="true">🚶 </span>}
        {r.leg(r.legMode[details?.mode ?? mode], t.minutes(minutes), distance, fromHotel)}
        {extras.map((extra) => ` · ${extra}`).join("")}
      </span>
      {details?.rides.map((ride) => (
        <span className="ride" key={`${ride.line}|${ride.from_stop}|${ride.to_stop}`}>
          <span
            className="line-chip"
            style={{ background: ride.line_color ?? undefined, color: ride.line_text_color ?? undefined }}
            title={[ride.agency, ride.headsign && r.towards(ride.headsign)].filter(Boolean).join(" · ") || undefined}
          >
            <span aria-hidden="true">{VEHICLE_ICONS[ride.vehicle] ?? "🚍"}</span>
            {ride.line}
          </span>
          <span>{r.ride(ride.from_stop, ride.to_stop, ride.stop_count)}</span>
        </span>
      ))}
    </div>
  );
}

const WEATHER_ICONS: Record<DayWeather["condition"], string> = {
  clear: "☀️",
  partly_cloudy: "⛅",
  cloudy: "☁️",
  fog: "🌫️",
  drizzle: "🌦️",
  rain: "🌧️",
  snow: "❄️",
  thunderstorm: "⛈️",
};

function WeatherLine({ weather, lang }: { weather: DayWeather; lang: Lang }) {
  const w = STRINGS[lang].weather;
  const typical = weather.source === "typical";
  const temp = (c: number) => `${Math.round(c)}°`;
  return (
    <p className={weather.is_rainy ? "weather rainy" : "weather"} title={typical ? w.typicalHint : undefined}>
      <span aria-hidden="true">{WEATHER_ICONS[weather.condition]}</span>
      {typical && <span className="muted">{w.typical}</span>}
      {/* "usually cloudy" rather than "usually Cloudy" */}
      <span>{typical ? w.conditions[weather.condition].toLocaleLowerCase(lang) : w.conditions[weather.condition]}</span>
      <span>
        {temp(weather.temp_max_c)} / <span className="muted">{temp(weather.temp_min_c)}</span>
      </span>
      {weather.precipitation_chance != null && weather.precipitation_chance > 0 && (
        <span className="muted">{w.rainChance(weather.precipitation_chance)}</span>
      )}
    </p>
  );
}
