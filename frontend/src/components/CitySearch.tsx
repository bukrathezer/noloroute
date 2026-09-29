import { type KeyboardEvent, useId, useMemo, useRef, useState } from "react";
import type { City } from "../api";
import { cityAliases, cityName, type Lang, STRINGS } from "../i18n";
import { searchKey } from "../text";

interface Props {
  cities: City[];
  value: City | null;
  onChange: (city: City | null) => void;
  lang: Lang;
}

/** Autocomplete over the supported cities: "ro" suggests Rome, "ist" suggests İstanbul. */
export function CitySearch({ cities, value, onChange, lang }: Props) {
  const t = STRINGS[lang].city;
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const matches = useMemo(() => {
    const key = searchKey(query.trim());
    if (!key) return cities;
    // Prefix matches on any name/alias first, then matches anywhere in the name.
    const score = (city: City) => {
      const keys = cityAliases(city).map(searchKey);
      if (keys.some((k) => k.startsWith(key))) return 0;
      if (keys.some((k) => k.includes(key))) return 1;
      return -1;
    };
    return cities
      .map((city) => ({ city, s: score(city) }))
      .filter((m) => m.s >= 0)
      .sort((a, b) => a.s - b.s)
      .map((m) => m.city);
  }, [cities, query]);

  const choose = (city: City) => {
    onChange(city);
    setQuery("");
    setOpen(false);
    inputRef.current?.blur();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, matches.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && open && matches[active]) {
      e.preventDefault();
      choose(matches[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const showing = open || !value;

  return (
    <div className="city-search">
      <div className="input-wrap">
        <svg className="input-icon" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && matches[active] ? `${listId}-${matches[active].id}` : undefined}
          placeholder={value ? cityName(value, lang) : t.placeholder}
          value={showing ? query : cityName(value, lang)}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={onKeyDown}
        />
        {value && (
          <button type="button" className="icon-button" aria-label={t.clear} onClick={() => onChange(null)}>
            ×
          </button>
        )}
      </div>
      {open && (
        <ul className="suggestions" id={listId} role="listbox">
          {matches.map((city, i) => (
            <li
              key={city.id}
              id={`${listId}-${city.id}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : undefined}
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(city)}
            >
              <span>{cityName(city, lang)}</span>
              <span className="muted">{t.places(city.poi_count)}</span>
            </li>
          ))}
          {matches.length === 0 && <li className="empty">{t.noResults(cities.length)}</li>}
        </ul>
      )}
    </div>
  );
}
