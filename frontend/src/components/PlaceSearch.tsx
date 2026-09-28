import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { type LatLng, placeAutocomplete, placeLocation, type PlaceSuggestion } from "../api";
import { type Lang, STRINGS } from "../i18n";

interface Props {
  /** Results are biased towards this point (the chosen city's centre). */
  near: LatLng;
  lang: Lang;
  onPick: (location: LatLng, label: string) => void;
}

const MIN_CHARS = 3;
const DEBOUNCE_MS = 300;

type Status = "idle" | "searching" | "done" | "error";

function newSessionToken() {
  return crypto.randomUUID();
}

/** Find the accommodation by name (hotel, address, landmark) via Google Places autocomplete. */
export function PlaceSearch({ near, lang, onPick }: Props) {
  const t = STRINGS[lang].hotel;
  const listId = useId();
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  // Every keystroke of one search and the final pick share a token, so Google bills them as one.
  const session = useRef(newSessionToken());
  const latest = useRef(0);
  const { lat, lng } = near;

  useEffect(() => {
    const text = query.trim();
    if (text.length < MIN_CHARS) {
      setSuggestions([]);
      setStatus("idle");
      return;
    }
    const id = ++latest.current;
    const timer = setTimeout(async () => {
      setStatus("searching");
      try {
        const result = await placeAutocomplete(text, { lat, lng }, session.current, lang);
        if (id !== latest.current) return; // a newer search is on its way
        setSuggestions(result);
        setActive(0);
        setStatus("done");
      } catch {
        if (id === latest.current) setStatus("error");
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // Depends on the coordinates, not the `near` object, which is re-created on every render.
  }, [query, lat, lng, lang]);

  const choose = async (suggestion: PlaceSuggestion) => {
    setOpen(false);
    try {
      const place = await placeLocation(suggestion.place_id, session.current, lang);
      onPick({ lat: place.lat, lng: place.lng }, suggestion.main_text);
      setQuery("");
      setSuggestions([]);
      setStatus("idle");
    } catch {
      setStatus("error");
    } finally {
      session.current = newSessionToken(); // the pick closes Google's billing session
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && open && suggestions[active]) {
      e.preventDefault();
      choose(suggestions[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const showList = open && query.trim().length >= MIN_CHARS && status !== "idle";

  return (
    <div className="city-search place-search">
      <div className="input-wrap">
        <svg className="input-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 21s-7-6.2-7-11a7 7 0 1 1 14 0c0 4.8-7 11-7 11z" />
          <circle cx="12" cy="10" r="2.5" />
        </svg>
        <input
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && suggestions[active] ? `${listId}-${active}` : undefined}
          placeholder={t.searchPlaceholder}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={onKeyDown}
        />
      </div>
      {showList && (
        <ul className="suggestions" id={listId} role="listbox">
          {status === "searching" && suggestions.length === 0 && <li className="empty">{t.searching}</li>}
          {status === "error" && <li className="empty">{t.searchError}</li>}
          {status === "done" && suggestions.length === 0 && <li className="empty">{t.noResults}</li>}
          {status !== "error" &&
            suggestions.map((s, i) => (
              <li
                key={s.place_id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                className={i === active ? "active stacked" : "stacked"}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(s)}
              >
                <span>{s.main_text}</span>
                {s.secondary_text && <span className="muted small">{s.secondary_text}</span>}
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
