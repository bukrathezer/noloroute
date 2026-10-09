import { type KeyboardEvent, lazy, Suspense, useId, useRef, useState } from "react";
import type { DateRange, Matcher } from "react-day-picker";
import { addDays, daysBetween, formatShortDay, fromIso, isoDate, MAX_DAYS_AHEAD, todayIso } from "../dates";
import { type Lang, STRINGS } from "../i18n";

const TripCalendar = lazy(() => import("./TripCalendar"));

const MAX_DAYS = 7; // the API's limit too

interface Props {
  /** "YYYY-MM-DD" of day 1, or "" to plan without dates. */
  startDate: string;
  days: number;
  onChange: (patch: { startDate?: string; days?: number }) => void;
  lang: Lang;
}

/**
 * Trip dates picked the way travel sites do it: on the calendar, the first click is the first
 * day of the trip and the second click the last. Without dates only a number of days is asked.
 */
export function DateRangeField({ startDate, days, onChange, lang }: Props) {
  const t = STRINGS[lang].dates;
  const calendarId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  // True between the two clicks: the first day is picked, the last isn't yet.
  const [pickingEnd, setPickingEnd] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);

  const today = todayIso();
  const lastBookable = addDays(today, MAX_DAYS_AHEAD);
  const endDate = startDate ? addDays(startDate, days - 1) : "";
  // While the last day is being picked, the trip can't grow past MAX_DAYS.
  const latestEnd = pickingEnd ? minIso(addDays(startDate, MAX_DAYS - 1), lastBookable) : lastBookable;

  const close = () => {
    setOpen(false);
    setPickingEnd(false);
    setHovered(null);
  };

  const pick = (day: Date) => {
    const iso = isoDate(day);
    if (pickingEnd && iso >= startDate) {
      // Second click: the last day (the first day again makes a one-day trip).
      onChange({ days: daysBetween(startDate, iso) + 1 });
      close();
    } else {
      // First click, or a day before the first one: a new trip starts on that day.
      onChange({ startDate: iso, days: 1 });
      setPickingEnd(true);
    }
  };

  const clearDates = () => {
    onChange({ startDate: "" });
    close();
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      close();
      triggerRef.current?.focus();
    }
  };

  const selected: DateRange | undefined = startDate
    ? { from: fromIso(startDate), to: pickingEnd ? undefined : fromIso(endDate) }
    : undefined;
  const disabled: Matcher[] = [{ before: fromIso(today) }, { after: fromIso(latestEnd) }];
  // Shades the days the trip would cover if the hovered day were clicked as the last one.
  const preview: DateRange | undefined =
    pickingEnd && hovered && hovered > startDate && hovered <= latestEnd
      ? { from: fromIso(addDays(startDate, 1)), to: fromIso(hovered) }
      : undefined;

  let summary = t.placeholder;
  if (startDate) {
    const first = formatShortDay(startDate, lang);
    const range = days === 1 ? first : t.range(first, formatShortDay(endDate, lang));
    summary = `${range} · ${t.dayCount(days)}`;
  }

  return (
    <div className="date-range">
      <div className="date-field">
        <button
          ref={triggerRef}
          type="button"
          className={startDate ? "date-trigger" : "date-trigger empty"}
          aria-expanded={open}
          aria-controls={calendarId}
          onClick={() => (open ? close() : setOpen(true))}
        >
          <svg className="input-icon" viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3.5" y="5" width="17" height="15.5" rx="2.5" />
            <path d="M3.5 10h17M8 3v4M16 3v4" />
          </svg>
          <span>{summary}</span>
        </button>
        {startDate && (
          <button type="button" className="icon-button" aria-label={t.clear} title={t.clear} onClick={clearDates}>
            ×
          </button>
        )}
      </div>

      {open && (
        <div id={calendarId} className="trip-calendar" onKeyDown={onKeyDown}>
          <Suspense fallback={<div className="calendar-loading" />}>
            <TripCalendar
              lang={lang}
              selected={selected}
              disabled={disabled}
              pendingStart={pickingEnd ? fromIso(startDate) : undefined}
              preview={preview}
              defaultMonth={fromIso(startDate || today)}
              startMonth={fromIso(today)}
              endMonth={fromIso(lastBookable)}
              status={pickingEnd ? t.pickEnd(MAX_DAYS) : t.pickStart}
              onPick={pick}
              onHover={(day) => setHovered(day && isoDate(day))}
            />
          </Suspense>
          <div className="calendar-actions">
            {startDate && (
              <button type="button" className="link-button" onClick={clearDates}>
                {t.noDates}
              </button>
            )}
            <button type="button" className="pill-button" onClick={close}>
              {t.done}
            </button>
          </div>
        </div>
      )}

      {!startDate && (
        <div className="no-dates">
          <span className="hint">{t.withoutDates}</span>
          <DayStepper days={days} onChange={(n) => onChange({ days: n })} lang={lang} />
        </div>
      )}
      {!startDate && <p className="hint">{t.hint}</p>}
    </div>
  );
}

function DayStepper({ days, onChange, lang }: { days: number; onChange: (days: number) => void; lang: Lang }) {
  const t = STRINGS[lang].days;
  return (
    <div className="stepper">
      <button type="button" aria-label={t.decrease} disabled={days <= 1} onClick={() => onChange(days - 1)}>
        −
      </button>
      <output aria-live="polite" aria-label={t.label}>
        {days}
      </output>
      <button type="button" aria-label={t.increase} disabled={days >= MAX_DAYS} onClick={() => onChange(days + 1)}>
        +
      </button>
    </div>
  );
}

const minIso = (a: string, b: string) => (a < b ? a : b);
