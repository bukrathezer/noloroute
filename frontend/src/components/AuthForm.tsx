import { type FormEvent, useEffect, useState } from "react";
import {
  ApiError,
  type CodePurpose,
  forgotPassword,
  googleLogin,
  login,
  register,
  resendCode,
  resetPassword,
  type TokenResponse,
  verifyEmail,
} from "../api";
import { type Lang, STRINGS } from "../i18n";
import { GoogleButton, useGoogleClientId } from "./GoogleButton";

export type AuthMode = "login" | "register";

// form: log in or sign up. code: the emailed code that confirms the address. forgot: the address
// to send a reset code to. reset: that code and the new password.
type Step = "form" | "code" | "forgot" | "reset";

const RESEND_SECONDS = 60; // the server sends code emails at least a minute apart

interface Props {
  lang: Lang;
  initialMode: AuthMode;
  /** `remember`: the user wants the login kept (in this browser, for weeks). */
  onAuthenticated: (result: TokenResponse, remember: boolean) => void;
}

/** Logging in and signing up, with the emailed codes: for the auth panel and the welcome screen. */
export function AuthForm({ lang, initialMode, onAuthenticated }: Props) {
  const t = STRINGS[lang].auth;
  const [step, setStep] = useState<Step>("form");
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [remember, setRemember] = useState(true);
  const [code, setCode] = useState("");
  const googleClientId = useGoogleClientId();
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
    setConfirm("");
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
    // A new password is typed twice: a typo would lock the account out.
    if (((step === "form" && mode === "register") || step === "reset") && password !== confirm) {
      setError(t.errors.passwordMismatch);
      return;
    }
    run(async () => {
      if (step === "form" && mode === "login") {
        try {
          onAuthenticated(await login(email, password, lang, remember), remember);
        } catch (err) {
          // The right password on an account still to confirm: a code is on its way.
          if (err instanceof ApiError && err.status === 403) toCode("code");
          else throw err;
        }
      } else if (step === "form") {
        await register(email, password, lang);
        toCode("code");
      } else if (step === "code") {
        onAuthenticated(await verifyEmail(email, code, password, remember), remember);
      } else if (step === "forgot") {
        await forgotPassword(email, lang);
        toCode("reset");
      } else {
        onAuthenticated(await resetPassword(email, code, password, remember), remember);
      }
    });
  };

  const signInWithGoogle = (credential: string) => {
    if (busy) return; // an e-mail login is under way
    return run(async () => {
      try {
        onAuthenticated(await googleLogin(credential, remember), remember);
      } catch (err) {
        const status = err instanceof ApiError ? err.status : -1;
        const detail = err instanceof ApiError ? err.message : "";
        if (status === 409) setError(detail === "link_with_password" ? t.errors.googleUsePassword : t.errors.googleMismatch);
        else if (status === 422) setError(t.errors.disposable);
        else if (status === 429) setError(t.errors.tooMany);
        else setError(t.errors.google);
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
        name="email"
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
  const confirmField = (label: string) => (
    <label className="auth-field">
      {label}
      <input
        type="password"
        name="password-confirm"
        autoComplete="new-password"
        required
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
      />
    </label>
  );
  const rememberBox = (
    <label className="auth-remember">
      <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
      {t.rememberMe}
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
                  setConfirm("");
                }}
              >
                {m === "login" ? t.loginTab : t.registerTab}
              </button>
            ))}
          </div>
          {googleClientId && (
            <>
              <GoogleButton clientId={googleClientId} lang={lang} onCredential={signInWithGoogle} />
              <div className="auth-or" aria-hidden="true">
                <span />
                {t.orWithEmail}
                <span />
              </div>
            </>
          )}
          {emailField}
          <label className="auth-field">
            {t.password}
            <input
              type="password"
              name="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={mode === "register" ? 8 : undefined}
              placeholder={mode === "register" ? t.passwordHint : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {mode === "register" && confirmField(t.confirmPassword)}
          <div className="auth-row">
            {rememberBox}
            {mode === "login" && (
              <button type="button" className="link-button auth-forgot" onClick={() => go("forgot")}>
                {t.forgot}
              </button>
            )}
          </div>
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
                name="password"
                autoComplete="new-password"
                required
                minLength={8}
                placeholder={t.passwordHint}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
          )}
          {step === "reset" && confirmField(t.newPasswordAgain)}
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
