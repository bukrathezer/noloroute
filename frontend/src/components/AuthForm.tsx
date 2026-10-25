import { type FormEvent, useEffect, useState } from "react";
import {
  ApiError,
  type CodePurpose,
  forgotPassword,
  login,
  register,
  resendCode,
  resetPassword,
  type TokenResponse,
  verifyEmail,
} from "../api";
import { type Lang, STRINGS } from "../i18n";

export type AuthMode = "login" | "register";

// form: log in or sign up. code: the emailed code that confirms the address. forgot: the address
// to send a reset code to. reset: that code and the new password.
type Step = "form" | "code" | "forgot" | "reset";

const RESEND_SECONDS = 60; // the server sends code emails at least a minute apart

interface Props {
  lang: Lang;
  initialMode: AuthMode;
  onAuthenticated: (result: TokenResponse) => void;
}

/** Logging in and signing up, with the emailed codes: for the auth panel and the welcome screen. */
export function AuthForm({ lang, initialMode, onAuthenticated }: Props) {
  const t = STRINGS[lang].auth;
  const [step, setStep] = useState<Step>("form");
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const go = (next: Step) => {
    setStep(next);
    setError(null);
    setCode("");
  };

  const toCode = (next: "code" | "reset") => {
    go(next);
    setPassword(next === "reset" ? "" : password);
    setCooldown(RESEND_SECONDS);
  };

  const fail = (err: unknown) => {
    const status = err instanceof ApiError ? err.status : -1;
    const detail = err instanceof ApiError ? err.message : "";
    if (status === 401) setError(t.errors.wrongCredentials);
    else if (status === 409) setError(t.errors.emailTaken);
    else if (status === 422) setError(detail === "disposable_email" ? t.errors.disposable : t.errors.invalid);
    else if (status === 400 || status === 403) setError(t.errors.invalidCode);
    else if (status === 429) setError(t.errors.tooMany);
    else if (status === 503) setError(t.errors.emailFailed);
    else setError(STRINGS[lang].errors.network);
  };

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      if (step === "form" && mode === "login") {
        try {
          onAuthenticated(await login(email, password, lang));
        } catch (err) {
          // The right password on an account still to confirm: a code is on its way.
          if (err instanceof ApiError && err.status === 403) toCode("code");
          else throw err;
        }
      } else if (step === "form") {
        await register(email, password, lang);
        toCode("code");
      } else if (step === "code") {
        onAuthenticated(await verifyEmail(email, code, password));
      } else if (step === "forgot") {
        await forgotPassword(email, lang);
        toCode("reset");
      } else {
        onAuthenticated(await resetPassword(email, code, password));
      }
    });
  };

  const resend = () =>
    run(async () => {
      const purpose: CodePurpose = step === "reset" ? "reset" : "verify";
      await resendCode(email, purpose, lang);
      setCooldown(RESEND_SECONDS);
    });

  const emailField = (
    <label className="auth-field">
      {t.email}
      <input
        type="email"
        autoComplete="email"
        required
        placeholder={t.emailPlaceholder}
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
    </label>
  );
  const codeField = (
    <label className="auth-field">
      {t.code}
      <input
        className="code-input"
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        required
        pattern="\d{6}"
        maxLength={6}
        placeholder="••••••"
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
      />
    </label>
  );
  const submitLabel =
    step === "form" ? (mode === "login" ? t.submitLogin : t.submitRegister)
    : step === "code" ? t.submitCode
    : step === "forgot" ? t.sendResetCode
    : t.submitReset;

  return (
    <form className="auth-form" onSubmit={submit}>
      {step === "form" && (
        <>
          <div className="segmented">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={mode === m}
                className={mode === m ? "selected" : undefined}
                onClick={() => {
                  setMode(m);
                  setError(null);
                }}
              >
                {m === "login" ? t.loginTab : t.registerTab}
              </button>
            ))}
          </div>
          {emailField}
          <label className="auth-field">
            {t.password}
            <input
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={mode === "register" ? 8 : undefined}
              placeholder={mode === "register" ? t.passwordHint : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {mode === "login" && (
            <button type="button" className="link-button auth-forgot" onClick={() => go("forgot")}>
              {t.forgot}
            </button>
          )}
        </>
      )}

      {(step === "code" || step === "reset") && (
        <>
          <p className="auth-notice">{(step === "code" ? t.codeSent : t.resetSent)(email)}</p>
          {codeField}
          {step === "reset" && (
            <label className="auth-field">
              {t.newPassword}
              <input
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                placeholder={t.passwordHint}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
          )}
        </>
      )}

      {step === "forgot" && (
        <>
          <p className="auth-notice">{t.forgotHint}</p>
          {emailField}
        </>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <button type="submit" className="primary-button" disabled={busy}>
        {busy ? t.working : submitLabel}
      </button>

      {step !== "form" && (
        <div className="auth-links">
          {(step === "code" || step === "reset") && (
            <button type="button" className="link-button" disabled={busy || cooldown > 0} onClick={resend}>
              {cooldown > 0 ? t.resendIn(cooldown) : t.resend}
            </button>
          )}
          <button type="button" className="link-button" onClick={() => go("form")}>
            {step === "forgot" ? t.backToLogin : t.changeEmail}
          </button>
        </div>
      )}
    </form>
  );
}
