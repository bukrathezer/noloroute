import { useEffect, useState } from "react";

// Chrome and Edge (Android, desktop) offer to install the site as an app through this event. It
// can come before React has mounted, so it is caught here, when the module first loads.
interface InstallPrompt extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let offered: InstallPrompt | null = null;
const listeners = new Set<() => void>();

function setOffered(prompt: InstallPrompt | null) {
  offered = prompt;
  for (const listener of listeners) listener();
}

window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault(); // our own button instead of the browser's banner
  setOffered(e as InstallPrompt);
});
window.addEventListener("appinstalled", () => setOffered(null));

/** Whether the browser offers installing the app, and the function that asks the user. */
export function useInstallPrompt(): { canInstall: boolean; install: () => Promise<void> } {
  const [prompt, setPrompt] = useState(offered);
  useEffect(() => {
    const update = () => setPrompt(offered);
    listeners.add(update);
    update();
    return () => {
      listeners.delete(update);
    };
  }, []);
  const install = async () => {
    const asked = offered;
    if (!asked) return;
    setOffered(null); // each offer can be used once: a second tap must not use it again
    try {
      await asked.prompt();
      await asked.userChoice;
    } catch {
      // Already used, or the browser changed its mind: nothing to do.
    }
  };
  return { canInstall: prompt !== null, install };
}

/** iPhones and iPads have no such offer: the site is added from the browser's Share menu. */
export function canAddToHomeScreen(): boolean {
  const ua = navigator.userAgent;
  // iPads have said "Macintosh" since iPadOS 13; touch tells them from Macs.
  const ios = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const installed =
    (navigator as Navigator & { standalone?: boolean }).standalone === true ||
    window.matchMedia("(display-mode: standalone)").matches;
  return ios && !installed;
}
