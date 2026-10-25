import type { TokenResponse } from "../api";
import { type Lang, STRINGS } from "../i18n";
import { AuthForm, type AuthMode } from "./AuthForm";

export type { AuthMode };

interface Props {
  lang: Lang;
  /** Shown above the form when the user got here by trying to save a route. */
  reason: "save" | null;
  initialMode?: AuthMode;
  onAuthenticated: (result: TokenResponse) => void;
  onBack: () => void;
}

export function AuthPanel({ lang, reason, initialMode = "login", onAuthenticated, onBack }: Props) {
  const t = STRINGS[lang].auth;
  return (
    <section className="auth-panel">
      <button type="button" className="link-button back" onClick={onBack}>
        {t.back}
      </button>
      <h2>{t.title}</h2>
      {reason === "save" && <p className="hint">{t.saveHint}</p>}
      <AuthForm lang={lang} initialMode={initialMode} onAuthenticated={onAuthenticated} />
    </section>
  );
}
