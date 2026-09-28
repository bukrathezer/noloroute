import type { CSSProperties } from "react";
import type { PlanResponse } from "../api";
import { type Lang, STRINGS } from "../i18n";
import { dayColor } from "../theme";

interface Props {
  plan: PlanResponse;
  lang: Lang;
  activeDay: number | null;
  onActiveDayChange: (day: number | null) => void;
  highlightedStop: string | null;
  onHighlightStop: (poiId: string | null) => void;
}

export function PlanResult({ plan, lang, activeDay, onActiveDayChange, highlightedStop, onHighlightStop }: Props) {
  const t = STRINGS[lang];
  const r = t.result;
  const stopCount = plan.days.reduce((n, d) => n + d.stops.length, 0);
  const visit = plan.days.reduce((n, d) => n + d.total_visit_minutes, 0);
  const travel = plan.days.reduce((n, d) => n + d.total_travel_minutes, 0);
  const cost = Number(plan.total_entry_cost);
  const allUnpriced = plan.unpriced_stop_count === stopCount;
  const km = (value: number) => value.toLocaleString(lang, { maximumFractionDigits: 1 });
  const days = activeDay ? plan.days.filter((d) => d.day_number === activeDay) : plan.days;

  return (
    <section className="plan-result" aria-live="polite">
      <h2>{r.summary(stopCount, plan.duration_days)}</h2>
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
            </h3>
            <span className="muted">
              {r.stopsCount(day.stops.length)} · {t.minutes(day.total_visit_minutes + day.total_travel_minutes)}
            </span>
          </header>
          {day.routing_source === "estimate" && day.stops.length > 0 && <p className="badge">{r.estimated}</p>}
          {day.stops.length === 0 ? (
            <p className="hint">{r.emptyDay}</p>
          ) : (
            <ol className="stops">
              {day.stops.map((stop) => (
                <li
                  key={stop.poi_id}
                  className={highlightedStop === stop.poi_id ? "highlighted" : undefined}
                  onMouseEnter={() => onHighlightStop(stop.poi_id)}
                  onMouseLeave={() => onHighlightStop(null)}
                >
                  <div className="leg">
                    {r.leg(
                      t.mode[plan.travel_mode],
                      t.minutes(stop.travel_minutes_from_previous),
                      km(stop.distance_km_from_previous),
                      stop.order_in_day === 1,
                    )}
                  </div>
                  <button type="button" className="stop" onClick={() => onHighlightStop(stop.poi_id)}>
                    <span className="stop-number">{stop.order_in_day}</span>
                    <span className="stop-body">
                      <span className="stop-name">{stop.name}</span>
                      <span className="muted">
                        {t.categories[stop.category] ?? stop.category} · {t.minutes(stop.visit_minutes)} {r.visit}
                        {stop.rating != null && ` · ★ ${stop.rating.toFixed(1)}`}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
              <li className="return">
                <div className="leg">
                  {r.leg(t.mode[plan.travel_mode], t.minutes(day.return_travel_minutes), km(day.return_distance_km), false)}
                </div>
                <div className="stop">
                  <span className="stop-number hotel" aria-hidden="true">
                    ⌂
                  </span>
                  <span className="stop-name">{r.backToHotel}</span>
                </div>
              </li>
            </ol>
          )}
        </article>
      ))}
    </section>
  );
}
