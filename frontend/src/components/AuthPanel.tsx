import { type FormEvent, useState } from "react";
import { ApiError, login, register, type TokenResponse } from "../api";
import { type Lang, STRINGS } from "../i18n";

export type AuthMode = "login" | "register";

/** The email and password form, for this panel and the welcome screen. */
export function useAuthForm(lang: Lang, onAuthenticated: (result: TokenResponse) => void, initialMode: AuthMode) {
  const t = STRINGS[lang].auth;
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = mode === "login" ? await login(email, password) : await register(email, password);
      onAuthenticated(result);
    } catch (err) {
      const status = err instanceof ApiError ? err.status : -1;
      if (status === 401) setError(t.errors.wrongCredentials);
      else if (status === 409) setError(t.errors.emailTaken);
      else if (status === 422) setError(t.errors.invalid);
      else if (status === 429) setError(t.errors.tooMany);
      else setError(STRINGS[lang].errors.network);
    } finally {
      setBusy(false);
    }
  };

  const switchTo = (next: AuthMode) => {
    setMode(next);
    setError(null);
  };

  return { mode, switchTo, email, setEmail, password, setPassword, busy, error, submit };
}

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
  const { mode, switchTo, email, setEmail, password, setPassword, busy, error, submit } = useAuthForm(
    lang,
    onAuthenticated,
    initialMode,
  );

  return (
    <section className="auth-panel">
      <button type="button" className="link-button back" onClick={onBack}>
        {t.back}
      </button>
      <h2>{mode === "login" ? t.loginTitle : t.registerTitle}</h2>
      {reason === "save" && <p className="hint">{t.saveHint}</p>}

      <form className="plan-form" onSubmit={submit}>
        <div className="field">
          <label className="field-label" htmlFor="auth-email">
            {t.email}
          </label>
          <div className="input-wrap">
            <input
              id="auth-email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="auth-password">
            {t.password}
          </label>
          <div className="input-wrap">
            <input
              id="auth-password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={mode === "register" ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {mode === "register" && <p className="hint">{t.passwordHint}</p>}
        </div>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="primary-button" disabled={busy}>
          {busy ? t.working : mode === "login" ? t.submitLogin : t.submitRegister}
        </button>
      </form>

      <button
        type="button"
        className="link-button switch-mode"
        onClick={() => switchTo(mode === "login" ? "register" : "login")}
      >
        {mode === "login" ? t.toRegister : t.toLogin}
      </button>
    </section>
  );
}
