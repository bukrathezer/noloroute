import type { MouseEvent, Ref } from "react";
import { type Lang, STRINGS } from "../i18n";
import { Icon } from "./Icon";

export type Section = "plan" | "guide" | "saved";

interface Props {
  lang: Lang;
  /** The menu item of the screen shown, if it has one. */
  section: Section | null;
  /** The signed-in account's e-mail, or null for a guest. */
  email: string | null;
  logoRef: Ref<HTMLAnchorElement>;
  onLogo: (e: MouseEvent<HTMLAnchorElement>) => void;
  onNavigate: (section: Section) => void;
  onLogin: () => void;
  onSwitchLanguage: () => void;
}

/** The app's header: logo, the main menu (planner, guide, saved routes), language and account. */
export function TopBar({ lang, section, email, logoRef, onLogo, onNavigate, onLogin, onSwitchLanguage }: Props) {
  const t = STRINGS[lang];
  const items = [
    { id: "plan", icon: "map", label: t.nav.plan },
    { id: "guide", icon: "compass", label: t.nav.guide },
    { id: "saved", icon: "bookmark", label: t.nav.saved },
  ] as const;

  return (
    <header className="topbar">
      <a className="logo" href="/" ref={logoRef} onClick={onLogo}>
        <img src="/favicon.svg" alt="" width={28} height={28} />
        <span>NoloRoute</span>
      </a>
      <nav className="main-nav" aria-label={t.nav.label}>
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-current={section === item.id ? "page" : undefined}
            onClick={() => onNavigate(item.id)}
          >
            <Icon name={item.icon} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="topbar-actions">
        <button type="button" className="pill-button language-button" onClick={onSwitchLanguage}>
          <Icon name="globe" size={16} />
          {t.switchLanguage}
        </button>
        {email ? (
          <button
            type="button"
            className="account-button"
            aria-label={t.nav.account}
            title={email}
            onClick={() => onNavigate("saved")}
          >
            {email.slice(0, 1).toUpperCase()}
          </button>
        ) : (
          <button type="button" className="login-button" onClick={onLogin}>
            {t.account.login}
          </button>
        )}
      </div>
    </header>
  );
}
