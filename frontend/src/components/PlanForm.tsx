import type { FormEvent } from "react";
import type { City, LatLng, TravelMode } from "../api";
import { cityName, type Lang, STRINGS } from "../i18n";
import { CitySearch } from "./CitySearch";
import { DateRangeField } from "./DateRangeField";
import { Icon, type IconName } from "./Icon";
import { PlaceSearch } from "./PlaceSearch";

export interface FormState {
  city: City | null;
  hotel: LatLng | null;
  /** Name of the searched place, or null when the pin was put on the map by hand. */
  hotelLabel: string | null;
  days: number;
  mode: TravelMode;
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
  /** Opens the travel guide on the chosen city; unset when it has no guide. */
  onShowGuide?: () => void;
  /** Phones: gets the panel out of the way so the stay can be tapped on the map. */
  onPickOnMap?: () => void;
}

const MODES: { mode: TravelMode; icon: IconName }[] = [
  { mode: "WALK", icon: "walk" },
  { mode: "TRANSIT", icon: "transit" },
  { mode: "DRIVE", icon: "car" },
];

export function PlanForm({ cities, form, onChange, onSubmit, loading, lang, onShowGuide, onPickOnMap }: Props) {
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
        <label className="field-label">{t.city.label}</label>
        <CitySearch
          cities={cities}
          value={form.city}
          onChange={(city) => onChange({ city, hotel: null, hotelLabel: null })}
          lang={lang}
        />
        {form.city && onShowGuide && (
          <button type="button" className="link-button guide-link" onClick={onShowGuide}>
            {t.guide.whenToGo(cityName(form.city, lang))} →
          </button>
        )}
      </div>

      <div className="field">
        <span className="field-label">{t.hotel.label}</span>
        {!form.city ? (
          <p className="hint">{t.hotel.pickCityFirst}</p>
        ) : form.hotel ? (
          <div className="hotel-chosen">
            <span className="pin-dot" aria-hidden="true" />
            <span className="hotel-label">{form.hotelLabel ?? t.hotel.pinnedOnMap}</span>
            <button type="button" className="link-button" onClick={() => onChange({ hotel: null, hotelLabel: null })}>
              {t.hotel.clear}
            </button>
          </div>
        ) : (
          <div className="hotel-empty">
            {cityCenter && (
              <PlaceSearch near={cityCenter} lang={lang} onPick={(hotel, hotelLabel) => onChange({ hotel, hotelLabel })} />
            )}
            <div className="quick-picks">
              {onPickOnMap && (
                <button type="button" className="chip-button" onClick={onPickOnMap}>
                  <Icon name="map" size={15} />
                  {t.hotel.pickOnMap}
                </button>
              )}
              {cityCenter && (
                <button
                  type="button"
                  className="chip-button"
                  onClick={() => onChange({ hotel: cityCenter, hotelLabel: null })}
                >
                  <Icon name="home" size={15} />
                  {t.hotel.centre}
                </button>
              )}
            </div>
            {!onPickOnMap && <p className="hint">{t.hotel.orClickMap}</p>}
          </div>
        )}
      </div>

      <div className="field">
        <span className="field-label">{t.dates.label}</span>
        <DateRangeField startDate={form.startDate} days={form.days} onChange={onChange} lang={lang} />
      </div>

      <div className="field">
        <span className="field-label" id="mode-label">
          {t.mode.label}
        </span>
        <div className="mode-options" role="radiogroup" aria-labelledby="mode-label">
          {MODES.map(({ mode, icon }) => (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={form.mode === mode}
              className={form.mode === mode ? "mode-option selected" : "mode-option"}
              onClick={() => onChange({ mode })}
            >
              <Icon name={icon} size={20} />
              <span className="mode-name">{t.mode[mode]}</span>
              <span className="mode-hint">{t.modeHint[mode]}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="form-submit">
        <button type="submit" className="primary-button" disabled={!canSubmit}>
          {loading ? t.planning : t.submit}
        </button>
        {!canSubmit && !loading && <p className="hint small">{t.submitHint}</p>}
      </div>
    </form>
  );
}
