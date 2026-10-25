import type { City, TokenResponse } from "../api";
import { type Lang, STRINGS } from "../i18n";
import { useAuthForm } from "./AuthPanel";
import { Globe } from "./Globe";

interface Props {
  lang: Lang;
  onSwitchLanguage: () => void;
  cities: City[];
  onAuthenticated: (result: TokenResponse) => void;
  onGuest: () => void;
  onGuide: () => void;
}

/** The first visit's screen: the turning globe, and logging in, signing up or going on as a guest. */
export default function Welcome({ lang, onSwitchLanguage, cities, onAuthenticated, onGuest, onGuide }: Props) {
  const t = STRINGS[lang];
  const w = t.welcome;
  const a = t.auth;
  const { mode, switchTo, email, setEmail, password, setPassword, busy, error, submit } = useAuthForm(
    lang,
    onAuthenticated,
    "login",
  );

  return (
    <div className="welcome">
      <header className="welcome-header">
        <span className="logo">
          <img src="/favicon.svg" alt="" width={34} height={34} />
          <span>NoloRoute</span>
        </span>
        <nav className="welcome-nav">
          <button type="button" className="link-button" onClick={onGuide}>
            {w.guide}
          </button>
          <button type="button" className="pill-button" onClick={onSwitchLanguage}>
            {t.switchLanguage}
          </button>
        </nav>
      </header>

      <main className="welcome-main">
        <div className="welcome-globe">
          <Globe cities={cities} lang={lang} label={w.globeLabel} />
        </div>

        <section className="welcome-card">
          <div className="welcome-intro">
            <span className="welcome-eyebrow">{w.eyebrow}</span>
            <h1>{w.title}</h1>
            <p>{w.lead}</p>
          </div>

          <form className="welcome-form" onSubmit={submit}>
            <div className="segmented">
              {(["login", "register"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  aria-pressed={mode === m}
                  className={mode === m ? "selected" : undefined}
                  onClick={() => switchTo(m)}
                >
                  {m === "login" ? a.loginTitle : w.registerTab}
                </button>
              ))}
            </div>
            <label className="welcome-field">
              {a.email}
              <input
                type="email"
                autoComplete="email"
                required
                placeholder={w.emailPlaceholder}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label className="welcome-field">
              {a.password}
              <input
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                required
                minLength={mode === "register" ? 8 : undefined}
                placeholder={mode === "register" ? a.passwordHint : undefined}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="primary-button" disabled={busy}>
              {busy ? a.working : mode === "login" ? a.submitLogin : a.submitRegister}
            </button>
          </form>

          <div className="welcome-or" aria-hidden="true">
            <span />
            {w.or}
            <span />
          </div>
          <button type="button" className="welcome-guest" onClick={onGuest}>
            {w.guest}
          </button>
          <p className="welcome-note">{w.note}</p>
        </section>
      </main>
    </div>
  );
}
