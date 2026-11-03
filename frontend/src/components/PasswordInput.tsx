import { type InputHTMLAttributes, useState } from "react";
import { type Lang, STRINGS } from "../i18n";

type Props = { lang: Lang } & Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

/** A password field with an eye button that shows or hides what was typed. */
export function PasswordInput({ lang, ...input }: Props) {
  const t = STRINGS[lang].auth;
  const [shown, setShown] = useState(false);
  const label = shown ? t.hidePassword : t.showPassword;
  return (
    <span className="password-input">
      <input {...input} type={shown ? "text" : "password"} />
      <button
        type="button"
        className="password-toggle"
        aria-label={label}
        aria-pressed={shown}
        title={label}
        onClick={() => setShown((s) => !s)}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
          <circle cx="12" cy="12" r="3" />
          {shown && <path d="M3 3l18 18" />}
        </svg>
      </button>
    </span>
  );
}
