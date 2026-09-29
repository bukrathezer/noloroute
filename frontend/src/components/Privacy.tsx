import { type Lang, STRINGS } from "../i18n";

/** What the app stores and which services it talks to (Ticketmaster's terms ask for this). */
export function Privacy({ lang, onBack }: { lang: Lang; onBack: () => void }) {
  const t = STRINGS[lang].privacy;
  return (
    <section className="privacy">
      <button type="button" className="link-button" onClick={onBack}>
        {t.back}
      </button>
      <h2>{t.title}</h2>
      {t.paragraphs.map((text) => (
        <p key={text}>{text}</p>
      ))}
    </section>
  );
}
