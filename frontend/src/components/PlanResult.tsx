import { type CSSProperties, useState } from "react";
import type { DayPlan, DayWeather, LegDetails, PlannedStop, PlanResponse, TravelMode } from "../api";
import { formatDay, formatMonth, fromIso } from "../dates";
import { type Lang, STRINGS } from "../i18n";
import { droppedNames, formatRating, stopName } from "../text";
import { dayColor } from "../theme";
import { DayEvents } from "./DayEvents";
import { Icon, type IconName } from "./Icon";
import { Suggestions } from "./Suggestions";

// When the planner has the traveller leave the hotel (DAY_START in app/services/transit_planner.py).
const DAY_START_MINUTES = 9 * 60;

interface Props {
  plan: PlanResponse;
  lang: Lang;
  activeDay: number | null;
  onActiveDayChange: (day: number | null) => void;
  highlightedStop: string | null;
  onHighlightStop: (poiId: string | null) => void;
  onRemoveStop: (poiId: string) => void;
  /** The stop being removed right now, if any. */
  removingStop: string | null;
  /** Swap a day with the one before (-1) or after (+1) it. */
  onMoveDay: (dayNumber: number, direction: -1 | 1) => void;
  /** The day being moved right now, if any. */
  movingDay: number | null;
}

export function PlanResult(props: Props) {
  const { plan, lang, activeDay, onActiveDayChange, highlightedStop, onHighlightStop } = props;
  const { onRemoveStop, removingStop, onMoveDay, movingDay } = props;
  const t = STRINGS[lang];
  const r = t.result;
  // The stop whose details (description, remove button) are open.
  const [openStop, setOpenStop] = useState<string | null>(null);
  const days = activeDay ? plan.days.filter((d) => d.day_number === activeDay) : plan.days;
  const transit = plan.travel_mode === "TRANSIT";
  // What the map shows: real rides (solid), estimated rides (dashed), or only walks.
  const legs = plan.days.flatMap((d) => [...d.stops.map((s) => s.leg_from_previous), d.return_leg]);
  const hasEstimated = legs.some((leg) => leg?.estimated);
  const hasRealRides = legs.some((leg) => leg?.mode === "TRANSIT" && !leg.estimated);
  // Plans saved before rides were estimated walked every leg where Google had no transit data.
  const allWalked = transit && !hasEstimated && plan.days.some((d) => d.transit_available === false);
  const money = (amount: string) =>
    Number(amount).toLocaleString(lang, {
      style: "currency",
      currency: plan.currency_code,
      maximumFractionDigits: Number.isInteger(Number(amount)) ? 0 : 2,
    });

  return (
    <section className="plan-result" aria-live="polite">
      {plan.days.length > 1 && (
        <div className="day-tabs" role="tablist" aria-label={r.daysLabel}>
          <button
            type="button"
            role="tab"
            aria-selected={activeDay === null}
            className={activeDay === null ? "selected" : undefined}
            onClick={() => onActiveDayChange(null)}
          >
            <span className="day-tab-label">{r.allDays}</span>
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
              <span className="day-tab-text">
                <span className="day-tab-label">{r.day(d.day_number)}</span>
                {tabDetail(d, lang) && <span className="day-tab-detail">{tabDetail(d, lang)}</span>}
              </span>
            </button>
          ))}
        </div>
      )}

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

      {days.map((day) => {
        const times = dayTimes(day);
        return (
          <article
            key={day.day_number}
            className={movingDay === day.day_number ? "day-card moving" : "day-card"}
            style={{ "--day": dayColor(day.day_number) } as CSSProperties}
          >
            <header className="day-head">
              <div>
                <h3>
                  <span className="swatch" aria-hidden="true" />
                  {r.day(day.day_number)}
                  {day.date && <span className="day-date">{formatDay(day.date, lang)}</span>}
                </h3>
                {day.stops.length > 0 && (
                  <p className="day-sub">
                    {r.stopsCount(day.stops.length)} · {clock(DAY_START_MINUTES)}–{clock(times.end)}
                  </p>
                )}
              </div>
              <div className="day-tools">
                {day.weather && <WeatherChip weather={day.weather} lang={lang} />}
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
              </div>
            </header>
            {day.rain_adjusted && <p className="hint rain-note">{r.rainNote}</p>}
            {droppedNames(day, lang).length > 0 && (
              <p className="hint">{r.dropped(droppedNames(day, lang).join(", "))}</p>
            )}
            {day.routing_source === "estimate" && day.stops.length > 0 && <p className="badge">{r.estimated}</p>}
            {day.stops.length === 0 ? (
              <p className="hint">{r.emptyDay}</p>
            ) : (
              <ol className="timeline">
                <li className="tl-row tl-end">
                  <span className="tl-time">{clock(DAY_START_MINUTES)}</span>
                  <span className="tl-rail">
                    <span className="tl-home">
                      <Icon name="home" size={12} />
                    </span>
                  </span>
                  <span className="tl-label">{r.leaveHotel}</span>
                </li>
                {day.stops.map((stop, i) => {
                  const open = openStop === stop.poi_id;
                  const name = stopName(stop, lang);
                  return (
                    <li
                      key={stop.poi_id}
                      className={
                        [
                          "tl-stop",
                          highlightedStop === stop.poi_id && "highlighted",
                          removingStop === stop.poi_id && "removing",
                        ]
                          .filter(Boolean)
                          .join(" ")
                      }
                      onMouseEnter={() => onHighlightStop(stop.poi_id)}
                      onMouseLeave={() => onHighlightStop(null)}
                    >
                      <div className="tl-row tl-leg">
                        <span className="tl-time" />
                        <span className="tl-rail">
                          <span className="tl-line" />
                        </span>
                        <LegLine
                          mode={plan.travel_mode}
                          details={stop.leg_from_previous}
                          minutes={stop.travel_minutes_from_previous}
                          km={stop.distance_km_from_previous}
                          fromHotel={stop.order_in_day === 1}
                          ferry={stop.ferry_from_previous ?? false}
                          lang={lang}
                        />
                      </div>
                      <div className="tl-row">
                        <span className="tl-time arrival">{clock(times.arrivals[i])}</span>
                        <span className="tl-rail">
                          <span className="stop-number">{stop.order_in_day}</span>
                        </span>
                        <div className="stop-card">
                          <button
                            type="button"
                            className="stop-main"
                            aria-expanded={open}
                            onClick={() => {
                              setOpenStop(open ? null : stop.poi_id);
                              onHighlightStop(stop.poi_id);
                            }}
                          >
                            <span className="stop-title">
                              <span className="stop-name">{name}</span>
                              {stop.rating != null && (
                                <span className="stop-rating">★ {formatRating(stop.rating, lang)}</span>
                              )}
                            </span>
                            <span className="stop-meta">
                              {t.categories[stop.category] ?? stop.category} · {t.minutes(stop.visit_minutes)}
                              {stop.hours &&
                                stop.hours !== "closed" &&
                                ` · ${stop.hours === "24/7" ? r.open247 : r.openHours(stop.hours)}`}
                            </span>
                            <StopTags stop={stop} money={money} lang={lang} />
                          </button>
                          {open && (
                            <div className="stop-details">
                              <StopDescription stop={stop} lang={lang} />
                              <div className="stop-actions">
                                <button
                                  type="button"
                                  className="small-button danger"
                                  aria-label={r.removeStop(name)}
                                  disabled={removingStop !== null}
                                  onClick={() => onRemoveStop(stop.poi_id)}
                                >
                                  {r.removeStopShort}
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    </li>
                  );
                })}
                <li className="tl-return">
                  <div className="tl-row tl-leg">
                    <span className="tl-time" />
                    <span className="tl-rail">
                      <span className="tl-line" />
                    </span>
                    <LegLine
                      mode={plan.travel_mode}
                      details={day.return_leg}
                      minutes={day.return_travel_minutes}
                      km={day.return_distance_km}
                      fromHotel={false}
                      ferry={day.return_ferry ?? false}
                      lang={lang}
                    />
                  </div>
                  <div className="tl-row tl-end">
                    <span className="tl-time">{clock(times.end)}</span>
                    <span className="tl-rail">
                      <span className="tl-home">
                        <Icon name="home" size={12} />
                      </span>
                    </span>
                    <span className="tl-label">{r.backToHotel}</span>
                  </div>
                </li>
              </ol>
            )}
            {day.stops.length > 0 && (
              <>
                <h4 className="extras-title">{r.forThisDay}</h4>
                {/* Keyed by the day's date and stops: a change starts the suggestions afresh. */}
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
              </>
            )}
          </article>
        );
      })}
      <p className="attribution">{r.timesNote}</p>
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

/** When the traveller reaches each stop and gets back, in minutes after midnight. */
function dayTimes(day: DayPlan): { arrivals: number[]; end: number } {
  let now = DAY_START_MINUTES;
  const arrivals = day.stops.map((stop) => {
    now += stop.travel_minutes_from_previous;
    const arrival = now;
    now += stop.visit_minutes;
    return arrival;
  });
  return { arrivals, end: now + day.return_travel_minutes };
}

/** "09:05" */
function clock(minutes: number): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(minutes / 60) % 24)}:${pad(minutes % 60)}`;
}

/** Under a day's name in its tab: the weekday and the day's high, as far as they are known. */
function tabDetail(day: DayPlan, lang: Lang): string {
  const parts: string[] = [];
  if (day.date) parts.push(fromIso(day.date).toLocaleDateString(lang, { weekday: "short" }));
  if (day.weather) parts.push(`${Math.round(day.weather.temp_max_c)}°`);
  return parts.join(" · ");
}

function StopTags({ stop, money, lang }: { stop: PlannedStop; money: (amount: string) => string; lang: Lang }) {
  const r = STRINGS[lang].result;
  const price = stop.entry_price == null ? null : Number(stop.entry_price);
  if (price === null && !stop.warning) return null;
  return (
    <span className="stop-tags">
      {price === 0 && <span className="stop-tag free">{r.free}</span>}
      {price !== null && price > 0 && <span className="stop-tag">{money(stop.entry_price as string)}</span>}
      {stop.warning && <span className={`stop-tag warn ${stop.warning}`}>{r.stopWarning[stop.warning]}</span>}
    </span>
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
  const r = STRINGS[lang].result;
  if (!description) return <p className="stop-description muted">{r.noDescription}</p>;
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

const LEG_ICONS: Record<TravelMode, IconName> = { WALK: "walk", TRANSIT: "transit", DRIVE: "car" };

interface LegLineProps {
  mode: TravelMode;
  /** Set in transit plans: whether this leg is walked or ridden, and on which lines. */
  details: LegDetails | null | undefined;
  minutes: number;
  km: number;
  fromHotel: boolean;
  /** The way crosses water by ferry, though walked or driven. */
  ferry: boolean;
  lang: Lang;
}

/** The travel line above a stop: "Walking 12 min · 0.9 km", plus the rides of a transit leg. */
function LegLine({ mode, details, minutes, km, fromHotel, ferry, lang }: LegLineProps) {
  const t = STRINGS[lang];
  const r = t.result;
  const legMode = details?.mode ?? mode;
  const distance = km.toLocaleString(lang, { maximumFractionDigits: 1 });
  const extras: string[] = [];
  if (ferry) extras.push(r.ferry);
  if (details?.estimated) extras.push(r.estimatedRide);
  if (details?.mode === "TRANSIT" && details.walk_minutes) extras.push(r.walkingPart(t.minutes(details.walk_minutes)));
  if (details?.alternative_mode && details.alternative_minutes != null) {
    extras.push(r.alternative[details.alternative_mode](t.minutes(details.alternative_minutes)));
  }

  return (
    <div className="leg">
      <span className="leg-text">
        <Icon name={LEG_ICONS[legMode]} size={13} />
        <span>
          {r.leg(r.legMode[legMode], t.minutes(minutes), distance, fromHotel)}
          {extras.map((extra) => ` · ${extra}`).join("")}
        </span>
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

function WeatherChip({ weather, lang }: { weather: DayWeather; lang: Lang }) {
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
