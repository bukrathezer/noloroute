import { useRef, useState } from "react";
import type { City, PlanResponse } from "../api";
import { addDays, fromIso } from "../dates";
import { cityName, type Lang, STRINGS } from "../i18n";
import { Icon, type IconName } from "./Icon";

// "dirty": a saved route was edited and the changes are not stored yet.
export type SaveState = "idle" | "saving" | "saved" | "dirty" | "error";

export type ShareState =
  | { status: "sharing" | "error" }
  /** `title`: for the phone's share sheet, e.g. "Paris · 2-day trip plan". */
  | { status: "done"; url: string; title: string };

const MODE_ICONS: Record<PlanResponse["travel_mode"], IconName> = { WALK: "walk", TRANSIT: "transit", DRIVE: "car" };

interface Props {
  plan: PlanResponse;
  city: City | null;
  /** The searched place's name; null for a pin put on the map, or the city centre. */
  stayLabel: string | null;
  lang: Lang;
  saveState: SaveState;
  onSave: () => void;
  onShowSaved: () => void;
  /** Sharing this plan by link, once asked for. */
  shareState: ShareState | null;
  onShare: () => void;
  /** The plan was opened from someone's link. */
  sharedWithYou: boolean;
  /** Back to the form, to change the trip. */
  onEdit: () => void;
}

/** The trip at a glance above its days: where, when, how, and the save and share buttons. */
export function TripSummary(props: Props) {
  const { plan, city, stayLabel, lang, saveState, onSave, onShowSaved, shareState, onShare, sharedWithYou, onEdit } =
    props;
  const t = STRINGS[lang];
  const s = t.summary;
  const stops = plan.days.reduce((n, d) => n + d.stops.length, 0);
  const visit = plan.days.reduce((n, d) => n + d.total_visit_minutes, 0);
  const travel = plan.days.reduce((n, d) => n + d.total_travel_minutes, 0);
  const atCentre =
    city?.center_lat === plan.accommodation.lat && city?.center_lng === plan.accommodation.lng;
  const stay = stayLabel ?? (atCentre ? s.cityCentre : s.yourPlace);

  return (
    <section className="trip-summary" aria-label={s.label}>
      <div className="trip-summary-head">
        <div>
          <p className="eyebrow">{s.eyebrow}</p>
          <h1>{city ? cityName(city, lang) : plan.city_id}</h1>
        </div>
        <button type="button" className="ghost-button" onClick={onEdit}>
          <Icon name="pencil" size={15} />
          {s.edit}
        </button>
      </div>
      <ul className="chips">
        <li>
          <Icon name="calendar" size={14} />
          {plan.start_date
            ? `${dateRange(plan.start_date, plan.duration_days, lang)} · ${t.dates.dayCount(plan.duration_days)}`
            : t.dates.dayCount(plan.duration_days)}
        </li>
        <li>
          <Icon name={MODE_ICONS[plan.travel_mode]} size={14} />
          {t.mode[plan.travel_mode]}
        </li>
        <li>
          <Icon name="home" size={14} />
          <span className="chip-text">{stay}</span>
        </li>
      </ul>
      <p className="trip-stats">{s.stats(t.result.stopsCount(stops), t.minutes(visit), t.minutes(travel))}</p>
      <div className="trip-actions">
        {saveState === "saved" ? (
          <button type="button" className="saved-badge" onClick={onShowSaved}>
            ✓ {t.save.saved}
          </button>
        ) : (
          <button type="button" className="primary-button" onClick={onSave} disabled={saveState === "saving"}>
            <Icon name="bookmark" size={17} />
            {saveState === "saving" ? t.save.saving : saveState === "dirty" ? t.save.saveChanges : t.save.button}
          </button>
        )}
        <button
          type="button"
          className="ghost-button"
          onClick={onShare}
          disabled={shareState?.status === "sharing"}
        >
          <Icon name="share" size={17} />
          {shareState?.status === "sharing" ? t.share.sharing : t.share.button}
        </button>
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
    </section>
  );
}

/** "7–8 Nov" / "7–8 Kas": the trip's days, as short as the language allows. */
function dateRange(start: string, days: number, lang: Lang): string {
  const first = fromIso(start);
  const last = fromIso(addDays(start, days - 1));
  const format = new Intl.DateTimeFormat(lang, { day: "numeric", month: "short" });
  return days === 1 ? format.format(first) : format.formatRange(first, last);
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
