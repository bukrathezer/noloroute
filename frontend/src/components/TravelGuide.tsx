import { type Ref, useEffect, useMemo, useRef, useState } from "react";
import type { City, Continent, Guide, GuideCity } from "../api";
import { countryName, monthName } from "../dates";
import { cityName, type Lang, STRINGS } from "../i18n";
import { Icon } from "./Icon";

interface Props {
  guide: Guide | null;
  failed: boolean;
  cities: City[];
  /** The list of cities couldn't be loaded: the guide only shows cities the app can plan. */
  citiesFailed: boolean;
  lang: Lang;
  /** 1 = January. */
  month: number;
  onMonthChange: (month: number) => void;
  /** The city whose month-by-month guide is open, if any. */
  cityId: string | null;
  onOpenCity: (id: string | null) => void;
  /** Start planning a trip to the city in that month. */
  onPlan: (city: City, month: number) => void;
}

const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

/** "Where should I go?": each month's best cities, and every city month by month, by continent. */
export function TravelGuide(props: Props) {
  const { guide, failed, cities, citiesFailed, lang, month, onMonthChange, cityId, onOpenCity, onPlan } = props;
  const t = STRINGS[lang].guide;
  const cityById = useMemo(() => new Map(cities.map((c) => [c.id, c])), [cities]);
  const [continent, setContinent] = useState<Continent | null>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const lastOpened = useRef<string | null>(null);
  const mounted = useRef(false);

  // Opening a city starts at its top, with focus on its name; going back returns focus to the
  // city that was opened. Not on the first render: arriving at the guide shouldn't jump.
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      lastOpened.current = cityId;
      return;
    }
    if (cityId) {
      lastOpened.current = cityId;
      pageRef.current?.scrollIntoView({ block: "start" });
      headingRef.current?.focus({ preventScroll: true });
    } else if (lastOpened.current) {
      pageRef.current?.querySelector<HTMLElement>(`[data-city="${lastOpened.current}"]`)?.focus();
      lastOpened.current = null;
    }
  }, [cityId]);

  if (failed) return <p className="error">{t.loadFailed}</p>;
  if (citiesFailed && cities.length === 0) return <p className="error">{STRINGS[lang].errors.loadCities}</p>;
  if (!guide || cities.length === 0) return <p className="hint">{t.loading}</p>;

  const entries = new Map(guide.cities.map((c) => [c.id, c]));
  const label = (c: City) => cityName(c, lang);
  const open = cityId ? cityById.get(cityId) : undefined;

  if (open) {
    return (
      <CityPage
        pageRef={pageRef}
        headingRef={headingRef}
        city={open}
        entry={entries.get(open.id)}
        guide={guide}
        lang={lang}
        month={month}
        onMonthChange={onMonthChange}
        onBack={() => onOpenCity(null)}
        onPlan={onPlan}
      />
    );
  }

  // Only cities the app can plan are listed.
  const picks = (guide.best[month - 1]?.picks ?? []).filter((p) => cityById.has(p.city_id));
  // Every city the app can plan, under its continent: from its guide entry, else from the city list.
  const groups = guide.continents
    .map((key) => ({
      key,
      cities: cities
        .filter((c) => (entries.get(c.id)?.continent ?? c.continent) === key)
        .sort((a, b) => label(a).localeCompare(label(b), lang)),
    }))
    .filter((g) => g.cities.length > 0);
  const shown = groups.find((g) => g.key === continent) ?? groups[0];

  return (
    <div className="guide-page" ref={pageRef}>
      <header className="guide-hero">
        <div>
          <h1>{t.title}</h1>
          <p className="tagline">{t.intro}</p>
        </div>
        <MonthPicker lang={lang} month={month} onChange={onMonthChange} />
      </header>

      {picks.length > 0 && (
        <section className="guide-section">
          <h2>{t.bestIn(monthName(month, lang))}</h2>
          <ol className="guide-best">
            {picks.map((p, i) => {
              const city = cityById.get(p.city_id) as City;
              return (
                <li key={p.city_id} className="guide-card">
                  <div className="guide-card-top">
                    <span className="guide-rank">{i + 1}</span>
                    <span className="muted small">{countryName(city.country_code ?? "", lang)}</span>
                  </div>
                  <h3>{label(city)}</h3>
                  <p className="guide-card-text">{p.text}</p>
                  <div className="guide-card-actions">
                    <button type="button" className="primary-button" onClick={() => onPlan(city, month)}>
                      {t.planCity}
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      data-city={p.city_id}
                      onClick={() => onOpenCity(p.city_id)}
                    >
                      {t.allMonths}
                    </button>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {shown && (
        <section className="guide-section">
          <div className="guide-section-head">
            <h2>{t.allCities}</h2>
            <div className="continent-tabs" role="tablist" aria-label={t.continentsLabel}>
              {groups.map((g) => (
                <button
                  key={g.key}
                  type="button"
                  role="tab"
                  aria-selected={g === shown}
                  onClick={() => setContinent(g.key)}
                >
                  {t.continents[g.key]} · {g.cities.length}
                </button>
              ))}
            </div>
          </div>
          <ul className="guide-cities">
            {shown.cities.map((c) => (
              <li key={c.id}>
                <button type="button" className="guide-city" data-city={c.id} onClick={() => onOpenCity(c.id)}>
                  <span>{label(c)}</span>
                  <span className="muted small">{countryName(c.country_code ?? "", lang)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

interface CityPageProps {
  pageRef: Ref<HTMLDivElement>;
  headingRef: Ref<HTMLHeadingElement>;
  city: City;
  /** Its month-by-month guide; cities added since the guide was written have none yet. */
  entry: GuideCity | undefined;
  guide: Guide;
  lang: Lang;
  month: number;
  onMonthChange: (month: number) => void;
  onBack: () => void;
  onPlan: (city: City, month: number) => void;
}

/** One city, month by month: pick the month to plan the trip for. */
function CityPage(props: CityPageProps) {
  const { pageRef, headingRef, city, entry, guide, lang, month, onMonthChange, onBack, onPlan } = props;
  const t = STRINGS[lang].guide;
  const name = cityName(city, lang);
  const best = (m: number) => guide.best[m - 1]?.picks.find((p) => p.city_id === city.id);

  return (
    <div className="guide-page" ref={pageRef}>
      <button type="button" className="link-button back" onClick={onBack}>
        <Icon name="back" size={16} />
        {t.allCities}
      </button>
      <header className="guide-city-head">
        <div>
          <h1 ref={headingRef} tabIndex={-1}>
            {name}
          </h1>
          <p className="muted">{countryName(city.country_code ?? "", lang)}</p>
        </div>
        <button type="button" className="primary-button" onClick={() => onPlan(city, month)}>
          {entry ? t.plan(name, monthName(month, lang)) : t.planCity}
        </button>
      </header>
      {entry?.note && <p className="guide-note">{entry.note}</p>}
      {entry ? (
        <>
          {MONTHS.some((m) => best(m)) && <p className="hint small">★ {t.starLegend}</p>}
          <ol className="guide-months">
            {MONTHS.map((m) => {
              const pick = best(m);
              return (
                <li key={m}>
                  <button
                    type="button"
                    className={["guide-month", pick && "best"].filter(Boolean).join(" ")}
                    aria-pressed={m === month}
                    onClick={() => onMonthChange(m)}
                  >
                    <span className="guide-month-name">
                      {monthName(m, lang)}
                      {pick && <span aria-label={t.starLegend}> ★</span>}
                    </span>
                    <span className="guide-month-text">{entry.months[m - 1]}</span>
                    {pick && (
                      <span className="guide-best-note">
                        <strong>{t.amongBest(monthName(m, lang))}</strong> {pick.text}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ol>
        </>
      ) : (
        <p className="empty-state">{t.noGuideYet}</p>
      )}
    </div>
  );
}

function MonthPicker(props: { lang: Lang; month: number; onChange: (m: number) => void }) {
  const { lang, month, onChange } = props;
  return (
    <div className="month-picker" role="radiogroup" aria-label={STRINGS[lang].guide.month}>
      {MONTHS.map((m) => (
        <button
          key={m}
          type="button"
          role="radio"
          aria-checked={m === month}
          aria-label={monthName(m, lang)}
          className={m === month ? "selected" : undefined}
          onClick={() => onChange(m)}
        >
          {monthName(m, lang, "short")}
        </button>
      ))}
    </div>
  );
}
