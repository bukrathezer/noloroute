import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the Vite server forwards API calls to the local FastAPI server, mirroring
// production where the API and this app are served from the same origin.
const API_TARGET = process.env.NOLOROUTE_API ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": API_TARGET,
      "/health": API_TARGET,
    },
  },
});
