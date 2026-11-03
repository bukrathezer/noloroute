import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { type AdminOverview, type AdminUser, ApiError, type DayCount, getAdminOverview, listAdminUsers } from "../api";
import { type Lang, STRINGS } from "../i18n";

const USERS_PER_PAGE = 25;

interface Props {
  lang: Lang;
  onBack: () => void;
  onUnauthorized: () => void;
}

/** The admin page: how many people use the app, and its accounts (only admins get here). */
export function AdminPanel({ lang, onBack, onUnauthorized }: Props) {
  const t = STRINGS[lang].admin;
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [failed, setFailed] = useState(false);

  const fail = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) onUnauthorized();
      else setFailed(true);
    },
    [onUnauthorized],
  );

  useEffect(() => {
    getAdminOverview().then(setOverview).catch(fail);
  }, [fail]);

  const number = (n: number) => n.toLocaleString(lang);

  return (
    <section className="saved-routes admin-panel">
      <button type="button" className="link-button back" onClick={onBack}>
        {t.back}
      </button>
      <h2>{t.title}</h2>

      {failed && (
        <p className="error" role="alert">
          {t.loadError}
        </p>
      )}
      {!overview && !failed && <p className="hint">{t.loading}</p>}

      {overview && (
        <>
          <div className="stat-grid">
            <Stat label={t.users} value={number(overview.users.total)} note={t.newThisWeek(overview.users.new_last_7_days)} />
            <Stat label={t.plans} value={number(overview.plans_last_30_days)} note={t.last30} />
            <Stat
              label={t.savedRoutes}
              value={number(overview.saved_routes)}
              note={t.byUsers(overview.users_with_saved_routes)}
            />
            <Stat
              label={t.shares}
              value={number(overview.shared_plans)}
              note={t.newThisWeek(overview.shared_plans_last_7_days)}
            />
          </div>

          <p className="hint small">
            {t.accountKinds(overview.users.verified, overview.users.with_google, overview.users.with_password)}
          </p>

          <DayChart title={t.plansByDay} days={overview.plans_by_day} lang={lang} />
          <DayChart title={t.signupsByDay} days={overview.signups_by_day} lang={lang} />

          <h3>{t.topCities}</h3>
          {overview.top_cities.length === 0 ? (
            <p className="empty-state">{t.nothingYet}</p>
          ) : (
            <table className="admin-table">
              <thead>
                <tr>
                  <th scope="col">{t.city}</th>
                  <th scope="col" title={t.last30}>
                    {t.plans}
                  </th>
                  <th scope="col">{t.savedShort}</th>
                  <th scope="col">{t.sharedShort}</th>
                </tr>
              </thead>
              <tbody>
                {overview.top_cities.map((c) => (
                  <tr key={c.city_id}>
                    <th scope="row">{(lang === "tr" && c.name_tr) || c.name}</th>
                    <td>{number(c.plans_last_30_days)}</td>
                    <td>{number(c.saved_routes)}</td>
                    <td>{number(c.shared_plans)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

        </>
      )}

      <UserList lang={lang} onError={fail} />
    </section>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="stat-card">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      <span className="muted small">{note}</span>
    </div>
  );
}

/** A bar per day of the last 30; hovering (or reading it aloud) gives the day and its count. */
function DayChart({ title, days, lang }: { title: string; days: DayCount[]; lang: Lang }) {
  const t = STRINGS[lang].admin;
  const most = Math.max(1, ...days.map((d) => d.count));
  const total = days.reduce((sum, d) => sum + d.count, 0);
  const busiest = days.reduce((a, b) => (b.count > a.count ? b : a), days[0]);
  const dayName = (d: DayCount) =>
    new Date(`${d.day}T00:00:00Z`).toLocaleDateString(lang, { day: "numeric", month: "short", timeZone: "UTC" });
  return (
    <figure className="day-chart">
      <figcaption>
        <span>{title}</span>
        <span className="muted small">{t.total(total)}</span>
        {busiest && busiest.count > 0 && (
          <span className="sr-only">{t.busiest(dayName(busiest), busiest.count)}</span>
        )}
      </figcaption>
      <ol className="day-bars" aria-hidden="true">
        {days.map((d) => (
          <li key={d.day} title={`${dayName(d)}: ${d.count}`}>
            <span style={{ height: `${(d.count / most) * 100}%` }} className={d.count ? undefined : "zero"} />
          </li>
        ))}
      </ol>
    </figure>
  );
}

function UserList({ lang, onError }: { lang: Lang; onError: (err: unknown) => void }) {
  const t = STRINGS[lang].admin;
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const latest = useRef(0); // the newest request: answers to older ones (an earlier search) are dropped

  const load = useCallback(
    async (q: string, offset: number) => {
      const request = ++latest.current;
      setLoading(true);
      try {
        const page = await listAdminUsers(q, USERS_PER_PAGE, offset);
        if (request !== latest.current) return;
        setUsers((list) => {
          if (offset === 0) return page.users;
          // An account that moved down a page (someone signed up meanwhile) isn't listed twice.
          const shown = new Set(list.map((u) => u.id));
          return [...list, ...page.users.filter((u) => !shown.has(u.id))];
        });
        setTotal(page.total);
      } catch (err) {
        if (request === latest.current) onError(err);
      } finally {
        if (request === latest.current) setLoading(false);
      }
    },
    [onError],
  );

  useEffect(() => {
    setUsers([]);
    setTotal(null);
    load(search, 0);
  }, [load, search]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSearch(query.trim());
  };

  const date = (iso: string) => new Date(iso).toLocaleDateString(lang, { dateStyle: "medium" });

  return (
    <>
      <h3>{t.accounts}</h3>
      <form className="admin-search" role="search" onSubmit={submit}>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t.searchPlaceholder}
          aria-label={t.searchPlaceholder}
          maxLength={200}
        />
        <button type="submit" className="pill-button">
          {t.search}
        </button>
      </form>
      <p className="hint small" aria-live="polite">
        {total === null ? (loading ? t.loading : "") : t.found(total)}
      </p>
      <ul className="saved-list admin-users">
        {users.map((u) => (
          <li key={u.id}>
            <div className="admin-user">
              <span className="stop-name">{u.email}</span>
              <span className="muted small">
                {t.joined(date(u.created_at))} ·{" "}
                {u.last_login_at ? t.lastLogin(date(u.last_login_at)) : t.neverLoggedIn}
              </span>
              <span className="admin-tags">
                {u.google && <span className="tag">Google</span>}
                {u.has_password && <span className="tag">{t.password}</span>}
                {!u.verified && <span className="tag warn">{t.unverified}</span>}
                <span className="tag">{t.routesCount(u.saved_routes)}</span>
              </span>
            </div>
          </li>
        ))}
      </ul>
      {total !== null && users.length < total && (
        <button type="button" className="pill-button more" disabled={loading} onClick={() => load(search, users.length)}>
          {loading ? t.loading : t.more}
        </button>
      )}
    </>
  );
}
