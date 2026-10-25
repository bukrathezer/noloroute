import type { City, TokenResponse } from "../api";
import { type Lang, STRINGS } from "../i18n";
import { AuthForm } from "./AuthForm";
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

          <AuthForm lang={lang} initialMode="login" onAuthenticated={onAuthenticated} />

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
