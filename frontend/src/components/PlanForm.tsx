import type { FormEvent } from "react";
import type { City, LatLng, TravelMode } from "../api";
import { addDays, formatDay, MAX_DAYS_AHEAD, todayIso } from "../dates";
import { type Lang, STRINGS } from "../i18n";
import { CitySearch } from "./CitySearch";
import { PlaceSearch } from "./PlaceSearch";

export const MAX_DAYS = 7;

export interface FormState {
  city: City | null;
  hotel: LatLng | null;
  /** Name of the searched place, or null when the pin was put on the map by hand. */
  hotelLabel: string | null;
  days: number;
  mode: TravelMode;
  budget: string;
  /** "YYYY-MM-DD" of day 1, or "" to plan without dates. */
  startDate: string;
}

interface Props {
  cities: City[];
  form: FormState;
  onChange: (patch: Partial<FormState>) => void;
  onSubmit: () => void;
  loading: boolean;
  lang: Lang;
}

export function PlanForm({ cities, form, onChange, onSubmit, loading, lang }: Props) {
  const t = STRINGS[lang];
  const canSubmit = Boolean(form.city && form.hotel) && !loading;
  const cityCenter =
    form.city?.center_lat != null && form.city.center_lng != null
      ? { lat: form.city.center_lat, lng: form.city.center_lng }
      : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (canSubmit) onSubmit();
  };

  return (
    <form className="plan-form" onSubmit={submit}>
      <div className="field">
        <label className="field-label">
          <span className="step">1</span>
          {t.city.label}
        </label>
        <CitySearch
          cities={cities}
          value={form.city}
          onChange={(city) => onChange({ city, hotel: null, hotelLabel: null })}
          lang={lang}
        />
      </div>

      <div className="field">
        <span className="field-label">
          <span className="step">2</span>
          {t.hotel.label}
        </span>
        {!form.city ? (
          <p className="hint">{t.hotel.pickCityFirst}</p>
        ) : form.hotel ? (
          <div className="hotel-chosen">
            <span className="pin-dot" aria-hidden="true" />
            <span className="hotel-label">
              {form.hotelLabel ?? t.hotel.pinnedOnMap}
              <span className="muted coords">
                {form.hotel.lat.toFixed(4)}, {form.hotel.lng.toFixed(4)}
              </span>
            </span>
            <button type="button" className="link-button" onClick={() => onChange({ hotel: null, hotelLabel: null })}>
              {t.hotel.clear}
            </button>
          </div>
        ) : (
          <div className="hotel-empty">
            {cityCenter && (
              <PlaceSearch near={cityCenter} lang={lang} onPick={(hotel, hotelLabel) => onChange({ hotel, hotelLabel })} />
            )}
            <p className="hint">{t.hotel.orClickMap}</p>
            {cityCenter && (
              <button
                type="button"
                className="link-button"
                onClick={() => onChange({ hotel: cityCenter, hotelLabel: null })}
              >
                {t.hotel.useCenter}
              </button>
            )}
          </div>
        )}
      </div>

      <div className="field-row">
        <div className="field">
          <span className="field-label">
            <span className="step">3</span>
            {t.days.label}
          </span>
          <div className="stepper">
            <button
              type="button"
              aria-label={t.days.decrease}
              disabled={form.days <= 1}
              onClick={() => onChange({ days: form.days - 1 })}
            >
              −
            </button>
            <output aria-live="polite">{form.days}</output>
            <button
              type="button"
              aria-label={t.days.increase}
              disabled={form.days >= MAX_DAYS}
              onClick={() => onChange({ days: form.days + 1 })}
            >
              +
            </button>
          </div>
        </div>

        <div className="field">
          <span className="field-label">{t.mode.label}</span>
          <div className="segmented" role="radiogroup" aria-label={t.mode.label}>
            {(["WALK", "DRIVE"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={form.mode === mode}
                className={form.mode === mode ? "selected" : undefined}
                onClick={() => onChange({ mode })}
              >
                {t.mode[mode]}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="field">
        <label className="field-label" htmlFor="start-date">
          {t.dates.label}
        </label>
        <div className="input-wrap">
          <input
            id="start-date"
            type="date"
            min={todayIso()}
            max={addDays(todayIso(), MAX_DAYS_AHEAD)}
            value={form.startDate}
            onChange={(e) => onChange({ startDate: e.target.value })}
          />
        </div>
        <p className="hint">
          {form.startDate
            ? t.dates.range(
                formatDay(form.startDate, lang, false),
                formatDay(addDays(form.startDate, form.days - 1), lang, false),
              )
            : t.dates.hint}
        </p>
      </div>

      <div className="field">
        <label className="field-label" htmlFor="budget">
          {t.budget.label} <span className="muted">({t.budget.optional})</span>
        </label>
        <div className="input-wrap">
          <input
            id="budget"
            type="number"
            inputMode="decimal"
            min={0}
            step={1}
            placeholder={t.budget.placeholder}
            value={form.budget}
            onChange={(e) => onChange({ budget: e.target.value })}
          />
          {form.city && <span className="suffix">{form.city.currency_code}</span>}
        </div>
      </div>

      <button type="submit" className="primary-button" disabled={!canSubmit}>
        {loading ? t.planning : t.submit}
      </button>
    </form>
  );
}
