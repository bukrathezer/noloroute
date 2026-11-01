import { useEffect, useRef, useState } from "react";
import { fetchAuthConfig } from "../api";
import type { Lang } from "../i18n";

// Google's own "Sign in with Google" button (Google Identity Services). Its script is loaded on
// first use; the client id comes from the server, and without one there is no button.
const GIS_SCRIPT = "https://accounts.google.com/gsi/client";
const MAX_WIDTH = 400; // Google draws the button 200-400 px wide

interface GoogleAccountsId {
  initialize(config: {
    client_id: string;
    callback: (response: { credential: string }) => void;
    ux_mode: "popup";
    auto_select: boolean;
  }): void;
  renderButton(parent: HTMLElement, options: Record<string, string | number>): void;
}

declare global {
  interface Window {
    google?: { accounts: { id: GoogleAccountsId } };
  }
}

let clientIdRequest: Promise<string | null> | null = null;
let scriptRequest: Promise<void> | null = null;

function loadClientId(): Promise<string | null> {
  clientIdRequest ??= fetchAuthConfig()
    .then((config) => config.google_client_id)
    .catch(() => {
      clientIdRequest = null; // asked again next time
      return null;
    });
  return clientIdRequest;
}

function loadScript(): Promise<void> {
  scriptRequest ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = GIS_SCRIPT;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      scriptRequest = null;
      script.remove();
      reject(new Error("Google sign-in script failed to load"));
    };
    document.head.appendChild(script);
  });
  return scriptRequest;
}

/** The Google client id, once the server has said it (null: no Google sign-in). */
export function useGoogleClientId(): string | null {
  const [clientId, setClientId] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    loadClientId().then((id) => {
      if (!cancelled) setClientId(id);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return clientId;
}

interface Props {
  clientId: string;
  lang: Lang;
  /** Google's signed statement of who signed in, for the server to check. */
  onCredential: (credential: string) => void;
}

export function GoogleButton({ clientId, lang, onCredential }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const handler = useRef(onCredential);
  handler.current = onCredential;

  useEffect(() => {
    let cancelled = false;
    loadScript()
      .then(() => {
        const google = window.google?.accounts.id;
        const parent = box.current;
        if (cancelled || !google || !parent) return;
        google.initialize({
          client_id: clientId,
          callback: (response) => handler.current(response.credential),
          ux_mode: "popup",
          auto_select: false,
        });
        // On the always-dark welcome screen, or in dark mode: Google's dark button.
        const dark = parent.closest(".welcome") || window.matchMedia("(prefers-color-scheme: dark)").matches;
        parent.replaceChildren();
        google.renderButton(parent, {
          type: "standard",
          theme: dark ? "filled_black" : "outline",
          size: "large",
          text: "continue_with",
          shape: "rectangular",
          logo_alignment: "center",
          locale: lang,
          width: Math.min(MAX_WIDTH, parent.clientWidth || MAX_WIDTH),
        });
      })
      .catch(() => {
        // Blocked or offline: e-mail sign-in still works.
      });
    return () => {
      cancelled = true;
    };
  }, [clientId, lang]);

  return <div ref={box} className="google-button" />;
}
