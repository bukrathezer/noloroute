import { type Lang, STRINGS } from "../i18n";

interface Props {
  lang: Lang;
  onRegister: () => void;
  onLogin: () => void;
  onClose: () => void;
}

/** A small, closable invitation for someone who opened a shared plan without an account. */
export function ShareInvite({ lang, onRegister, onLogin, onClose }: Props) {
  const s = STRINGS[lang].invite;
  return (
    <aside className="share-invite" aria-label={s.title}>
      <div className="share-invite-body">
        <strong>{s.title}</strong>
        <span>{s.text}</span>
        <div className="share-invite-actions">
          <button type="button" className="primary-button" onClick={onRegister}>
            {s.register}
          </button>
          <button type="button" className="secondary-button" onClick={onLogin}>
            {s.login}
          </button>
        </div>
      </div>
      <button type="button" className="share-invite-close" aria-label={s.close} title={s.close} onClick={onClose}>
        ×
      </button>
    </aside>
  );
}
