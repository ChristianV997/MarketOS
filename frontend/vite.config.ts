import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

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
      // api/routes/services.py's router is mounted at the literal prefix
      // /api/services (backend/api.py: APIRouter(prefix="/api/services")),
      // so this must forward unchanged — no path rewrite. The previous
      // strip-/api rewrite was dead configuration: nothing in the
      // frontend called an /api/* path until services.* did.
      "/api": {
        target: "http://localhost:3000",
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
