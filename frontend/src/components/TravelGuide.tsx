import { useEffect, useMemo, useRef } from "react";
import type { City, Continent, Guide, GuideCity } from "../api";
import { countryName, monthName } from "../dates";
import { cityName, type Lang, STRINGS } from "../i18n";

/** What the map should show for the guide: a country's cities, or one city. */
export type GuideFocus = { kind: "country"; code: string } | { kind: "city"; id: string } | null;

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
  onFocus: (focus: GuideFocus) => void;
  /** Start planning a trip to the city in that month. */
  onPlan: (city: City, month: number) => void;
}

const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

/** "Where should I go?": each month's best cities, and every city month by month, by continent. */
export function TravelGuide(props: Props) {
  const { guide, failed, cities, citiesFailed, lang, month, onMonthChange, cityId, onOpenCity, onFocus, onPlan } =
    props;
  const t = STRINGS[lang].guide;
  const cityById = useMemo(() => new Map(cities.map((c) => [c.id, c])), [cities]);
  const sectionRef = useRef<HTMLElement>(null);
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
      sectionRef.current?.scrollIntoView({ block: "start" });
      headingRef.current?.focus({ preventScroll: true });
    } else if (lastOpened.current) {
      sectionRef.current?.querySelector<HTMLElement>(`[data-city="${lastOpened.current}"]`)?.focus();
      lastOpened.current = null;
    }
  }, [cityId]);

  if (failed) return <p className="error">{t.loadFailed}</p>;
  if (citiesFailed && cities.length === 0) return <p className="error">{STRINGS[lang].errors.loadCities}</p>;
  if (!guide || cities.length === 0) return <p className="hint">{t.loading}</p>;

  // Only cities the app can plan are listed.
  const guideCities = guide.cities.filter((c) => cityById.has(c.id));
  const open = cityId ? guideCities.find((c) => c.id === cityId) : undefined;
  const label = (c: GuideCity) => cityName(cityById.get(c.id) as City, lang);

  if (open) {
    const city = cityById.get(open.id) as City;
    const bestMonths = new Set(
      guide.best.filter((m) => m.picks.some((p) => p.city_id === open.id)).map((m) => m.month),
    );
    const bestText = guide.best[month - 1]?.picks.find((p) => p.city_id === open.id)?.text;
    return (
      <section className="guide" ref={sectionRef}>
        <button type="button" className="link-button guide-back" onClick={() => onOpenCity(null)}>
          ← {t.allCities}
        </button>
        <header className="guide-city-header">
          <h2 ref={headingRef} tabIndex={-1}>
            {label(open)}
          </h2>
          <span className="muted">{countryName(open.country_code, lang)}</span>
        </header>
        {open.note && <p className="guide-note">{open.note}</p>}
        <MonthPicker lang={lang} month={month} onChange={onMonthChange} starred={bestMonths} />
        {bestMonths.size > 0 && <p className="hint small">★ {t.starLegend}</p>}
        <article className="guide-month">
          <h3>{monthName(month, lang)}</h3>
          <p>{open.months[month - 1]}</p>
          {bestText && (
            <p className="guide-best-note">
              <strong>★ {t.amongBest(monthName(month, lang))}</strong> {bestText}
            </p>
          )}
        </article>
        <button type="button" className="primary-button" onClick={() => onPlan(city, month)}>
          {t.plan(label(open), monthName(month, lang))}
        </button>
      </section>
    );
  }

  const picks = (guide.best[month - 1]?.picks ?? []).filter((p) => cityById.has(p.city_id));
  // Continent -> country -> cities, countries and cities in alphabetical order for the language.
  const byContinent = guide.continents
    .map((continent) => {
      const countries = new Map<string, GuideCity[]>();
      for (const c of guideCities.filter((c) => c.continent === continent)) {
        countries.set(c.country_code, [...(countries.get(c.country_code) ?? []), c]);
      }
      const sorted = [...countries.entries()]
        .map(([code, list]) => ({
          code,
          name: countryName(code, lang),
          cities: list.sort((a, b) => label(a).localeCompare(label(b), lang)),
        }))
        .sort((a, b) => a.name.localeCompare(b.name, lang));
      return { continent, countries: sorted };
    })
    .filter((c) => c.countries.length > 0);

  return (
    <section className="guide" ref={sectionRef}>
      <p className="tagline">{t.intro}</p>
      <MonthPicker lang={lang} month={month} onChange={onMonthChange} />

      {picks.length > 0 && <h2 className="guide-heading">{t.bestIn(monthName(month, lang))}</h2>}
      <ol className="guide-picks">
        {picks.map((p) => {
          const city = cityById.get(p.city_id) as City;
          return (
            <li key={p.city_id}>
              <button
                type="button"
                className="guide-pick"
                data-city={p.city_id}
                onClick={() => onOpenCity(p.city_id)}
              >
                <span className="guide-pick-name">
                  {cityName(city, lang)}{" "}
                  <span className="muted">· {countryName(city.country_code ?? "", lang)}</span>
                </span>
                <span className="guide-pick-text">{p.text}</span>
              </button>
              <button type="button" className="link-button guide-plan-link" onClick={() => onPlan(city, month)}>
                {t.planShort} →
              </button>
            </li>
          );
        })}
      </ol>

      <h2 className="guide-heading">{t.allCities}</h2>
      {byContinent.map(({ continent, countries }) => (
        <div key={continent} className="guide-continent">
          <h3>{t.continents[continent as Continent]}</h3>
          <ul>
            {countries.map((country) => (
              <li key={country.code} className="guide-country">
                <button
                  type="button"
                  className="link-button guide-country-name"
                  title={t.showOnMap(country.name)}
                  onClick={() => onFocus({ kind: "country", code: country.code })}
                >
                  {country.name}
                </button>
                <span className="guide-country-cities">
                  {country.cities.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      className="guide-city-chip"
                      data-city={c.id}
                      onClick={() => onOpenCity(c.id)}
                    >
                      {label(c)}
                    </button>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

function MonthPicker(props: { lang: Lang; month: number; onChange: (m: number) => void; starred?: Set<number> }) {
  const { lang, month, onChange, starred } = props;
  return (
    <div className="month-picker" role="radiogroup" aria-label={STRINGS[lang].guide.month}>
      {MONTHS.map((m) => (
        <button
          key={m}
          type="button"
          role="radio"
          aria-checked={m === month}
          aria-label={starred?.has(m) ? `${monthName(m, lang)}, ★` : monthName(m, lang)}
          className={m === month ? "selected" : undefined}
          onClick={() => onChange(m)}
        >
          {monthName(m, lang, "short")}
          {starred?.has(m) && (
            <span className="month-star" aria-hidden="true">
              {" "}
              ★
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
