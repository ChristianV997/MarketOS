import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

const BACKEND_TARGET = "http://localhost:3000";

// Dashboard polling routes live at the backend root, not under /api.
const BACKEND_ROOT_PROXY =
  "^/(metrics|snapshot|opportunities|campaigns|creatives|geo|alerts|risk|agents|runtime|prediction_errors|simulation|playbook|portfolio|capital_allocation|macro|causal|accounts|phase|bandit|cycle|runner|tiktok|health|ready|status|events|commerce)(/|$)";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      [BACKEND_ROOT_PROXY]: {
        target: BACKEND_TARGET,
        changeOrigin: true,
      },
      "/api": {
        target: BACKEND_TARGET,
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:3000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
