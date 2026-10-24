import { type CSSProperties, useRef, useState } from "react";
import type { DayWeather, LegDetails, PlannedStop, PlanResponse, TravelMode } from "../api";
import { formatDay, formatMonth } from "../dates";
import { type Lang, STRINGS } from "../i18n";
import { droppedNames, formatRating, stopName } from "../text";
import { dayColor } from "../theme";
import { DayEvents } from "./DayEvents";
import { Suggestions } from "./Suggestions";

// "dirty": a saved route was edited and the changes are not stored yet.
export type SaveState = "idle" | "saving" | "saved" | "dirty" | "error";

export type ShareState =
  | { status: "sharing" | "error" }
  /** `title`: for the phone's share sheet, e.g. "Paris · 2-day trip plan". */
  | { status: "done"; url: string; title: string };

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
  /** Swap a day with the one before (-1) or after (+1) it. */
  onMoveDay: (dayNumber: number, direction: -1 | 1) => void;
  /** The day being moved right now, if any. */
  movingDay: number | null;
  /** Sharing this plan by link, once asked for. */
  shareState: ShareState | null;
  onShare: () => void;
  /** The plan was opened from someone's link. */
  sharedWithYou: boolean;
}

export function PlanResult(props: Props) {
  const { plan, lang, activeDay, onActiveDayChange, highlightedStop, onHighlightStop } = props;
  const { saveState, onSave, onShowSaved, onRemoveStop, removingStop, onMoveDay, movingDay } = props;
  const { shareState, onShare, sharedWithYou } = props;
  const t = STRINGS[lang];
  const r = t.result;
  const stopCount = plan.days.reduce((n, d) => n + d.stops.length, 0);
  const visit = plan.days.reduce((n, d) => n + d.total_visit_minutes, 0);
  const travel = plan.days.reduce((n, d) => n + d.total_travel_minutes, 0);
  const cost = Number(plan.total_entry_cost);
  const allUnpriced = plan.unpriced_stop_count === stopCount;
  const days = activeDay ? plan.days.filter((d) => d.day_number === activeDay) : plan.days;
  const transit = plan.travel_mode === "TRANSIT";
  // What the map shows: real rides (solid), estimated rides (dashed), or only walks.
  const legs = plan.days.flatMap((d) => [...d.stops.map((s) => s.leg_from_previous), d.return_leg]);
  const hasEstimated = legs.some((leg) => leg?.estimated);
  const hasRealRides = legs.some((leg) => leg?.mode === "TRANSIT" && !leg.estimated);
  // Plans saved before rides were estimated walked every leg where Google had no transit data.
  const allWalked = transit && !hasEstimated && plan.days.some((d) => d.transit_available === false);
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
        <div className="result-actions">
          <button
            type="button"
            className="secondary-button"
            onClick={onShare}
            disabled={shareState?.status === "sharing"}
          >
            {shareState?.status === "sharing" ? t.share.sharing : t.share.button}
          </button>
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
      </div>
      {sharedWithYou && <p className="hint shared-note">{t.share.sharedWithYou}</p>}
      {saveState === "error" && (
        <p className="error" role="alert">
          {t.save.error}
        </p>
      )}
      {shareState?.status === "error" && (
        <p className="error" role="alert">
          {t.share.error}
        </p>
      )}
      {/* Keyed by the link: a new one starts without "Copied". */}
      {shareState?.status === "done" && (
        <ShareBox key={shareState.url} url={shareState.url} title={shareState.title} lang={lang} />
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
      {transit && hasEstimated && <p className="hint">{r.noTransit}</p>}
      {allWalked && <p className="hint">{r.allWalked}</p>}
      {transit && (
        <p className="hint">
          {hasEstimated ? (hasRealRides ? r.mapLegendMixed : r.mapLegendEstimated) : r.mapLegend}
        </p>
      )}

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
          className={movingDay === day.day_number ? "day-card moving" : "day-card"}
          style={{ "--day": dayColor(day.day_number) } as CSSProperties}
        >
          <header>
            <h3>
              <span className="swatch" aria-hidden="true" />
              {r.day(day.day_number)}
              {day.date && <span className="day-date">{formatDay(day.date, lang)}</span>}
            </h3>
            <span className="day-meta">
              <span className="muted">
                {r.stopsCount(day.stops.length)} · {t.minutes(day.total_visit_minutes + day.total_travel_minutes)}
              </span>
              {plan.days.length > 1 && (
                <span className="move-day">
                  {([-1, 1] as const).map((direction) => {
                    const label = direction < 0 ? r.moveDay.earlier : r.moveDay.later;
                    const edge = direction < 0 ? day.day_number === 1 : day.day_number === plan.days.length;
                    return (
                      <button
                        key={direction}
                        type="button"
                        aria-label={label(day.day_number)}
                        title={label(day.day_number)}
                        disabled={edge || movingDay !== null}
                        onClick={() => onMoveDay(day.day_number, direction)}
                      >
                        {direction < 0 ? "↑" : "↓"}
                      </button>
                    );
                  })}
                </span>
              )}
            </span>
          </header>
          {day.weather && <WeatherLine weather={day.weather} lang={lang} />}
          {day.rain_adjusted && <p className="hint rain-note">{r.rainNote}</p>}
          {droppedNames(day, lang).length > 0 && <p className="hint">{r.dropped(droppedNames(day, lang).join(", "))}</p>}
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
                        <span className="stop-name">{stopName(stop, lang)}</span>
                        <span className="muted">
                          {t.categories[stop.category] ?? stop.category} · {t.minutes(stop.visit_minutes)} {r.visit}
                          {stop.rating != null && ` · ★ ${formatRating(stop.rating, lang)}`}
                          {stop.entry_price != null && ` · ${money(stop.entry_price)}`}
                        </span>
                        {stop.hours && stop.hours !== "closed" && (
                          <span className="muted small">
                            {stop.hours === "24/7" ? r.open247 : r.openHours(stop.hours)}
                          </span>
                        )}
                        {stop.warning && (
                          <span className={`stop-warning ${stop.warning}`}>
                            <span aria-hidden="true">{stop.warning === "rain" ? "🌧️ " : "⚠ "}</span>
                            {r.stopWarning[stop.warning]}
                          </span>
                        )}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="remove-stop"
                      aria-label={r.removeStop(stopName(stop, lang))}
                      title={r.removeStop(stopName(stop, lang))}
                      disabled={removingStop !== null}
                      onClick={() => onRemoveStop(stop.poi_id)}
                    >
                      ×
                    </button>
                  </div>
                  <StopDescription stop={stop} lang={lang} />
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
            <div className="day-extras" key={`${day.date ?? ""}|${day.stops.map((s) => s.poi_id).join(",")}`}>
              {(["food", "nightlife"] as const).map((kind) => (
                <Suggestions
                  // Google answers in the language asked for, so a switch fetches them again.
                  key={`${kind}|${lang}`}
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
      {plan.days.some((d) => d.stops.some((s) => descriptionOf(s, lang))) && (
        <p className="attribution">
          {r.descriptionsNote(
            <a key="wiki" href={`https://${lang}.wikipedia.org/`} target="_blank" rel="noreferrer">
              {r.wikipedia}
            </a>,
            <a
              key="license"
              href={`https://creativecommons.org/licenses/by-sa/4.0/deed.${lang}`}
              target="_blank"
              rel="noreferrer"
            >
              CC BY-SA 4.0
            </a>,
            plan.days.some((d) => d.stops.some((s) => descriptionOf(s, lang)?.translated)),
          )}
        </p>
      )}
    </section>
  );
}

/** The link, ready to copy or (on phones) to send through another app. */
function ShareBox({ url, title, lang }: { url: string; title: string; lang: Lang }) {
  const s = STRINGS[lang].share;
  const input = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState(false);
  const canSend = typeof navigator.share === "function";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // No clipboard access: select the link so it can be copied by hand.
      input.current?.select();
    }
  };

  return (
    <div className="share-box">
      <label>
        <span className="muted small">{s.linkLabel}</span>
        <input ref={input} type="text" readOnly value={url} onFocus={(e) => e.currentTarget.select()} />
      </label>
      <div className="share-actions">
        <button type="button" className="pill-button" onClick={copy}>
          {copied ? s.copied : s.copy}
        </button>
        {canSend && (
          // Closing the share sheet without sending rejects: nothing to do then.
          <button type="button" className="pill-button" onClick={() => navigator.share({ title, url }).catch(() => {})}>
            {s.send}
          </button>
        )}
      </div>
      <p className="muted small">{s.note}</p>
    </div>
  );
}

interface Description {
  text: string;
  /** The language of the Wikipedia article it comes from. */
  article: Lang;
  /** Machine-translated from that article (the place has none in the page's language). */
  translated: boolean;
}

/** The stop's description in the page's language, or null: never one in the other language. */
function descriptionOf(stop: PlannedStop, lang: Lang): Description | null {
  if (!stop.wikidata_id) return null;
  const text = lang === "tr" ? stop.description_tr : stop.description_en;
  if (!text) return null;
  const translated = stop.description_translated === lang;
  return { text, article: translated ? (lang === "tr" ? "en" : "tr") : lang, translated };
}

function StopDescription({ stop, lang }: { stop: PlannedStop; lang: Lang }) {
  const description = descriptionOf(stop, lang);
  if (!description) return null;
  const r = STRINGS[lang].result;
  // Wikidata forwards to the item's article in that language.
  const article = `https://www.wikidata.org/wiki/Special:GoToLinkedPage/${description.article}wiki/${stop.wikidata_id}`;
  return (
    <p className="stop-description">
      <span>{description.text}</span>{" "}
      <a href={article} target="_blank" rel="noreferrer" hrefLang={description.article}>
        {r.wikipedia}
      </a>
      {/* Google's terms for Cloud Translation ask for this credit next to translated text. */}
      {description.translated && <span className="translated-by"> · {r.translatedByGoogle}</span>}
    </p>
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
  if (details?.estimated) extras.push(r.estimatedRide);
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
            style={{ background: hexColor(ride.line_color), color: hexColor(ride.line_text_color) }}
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

/** A colour code like "#ffcd00", or undefined for anything else (shared plans come from strangers). */
function hexColor(value: string | null): string | undefined {
  return value && /^#[0-9a-f]{6}$/i.test(value) ? value : undefined;
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
