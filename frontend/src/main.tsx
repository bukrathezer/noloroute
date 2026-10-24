import "leaflet/dist/leaflet.css";
import "./styles.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Makes the site installable as an app, with a page of its own when opened offline (public/sw.js).
// Not in development, where it would only get in the way of Vite's reloading.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Not installable then; the site works the same.
    });
  });
}
