import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/**
 * M04 — Skill Graph & MNEMOS Memory, on its reserved port 5204 (PORTS.txt).
 *
 * The module's first screen (2026-10-03). Platform_Shell mounts the same
 * `src/routes.tsx` at `/skills`, so what you fix here is what students get.
 */
const API_TARGET = process.env.VITE_API_BASE ?? "http://127.0.0.1:8104";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: {
    // @ai/core ships TypeScript source rather than a build, so Vite must
    // transform it instead of pre-bundling it as an opaque dependency.
    exclude: ["@ai/core"],
  },
  server: {
    port: 5204,
    proxy: {
      "/v1": { target: API_TARGET, changeOrigin: true },
      "/health": { target: API_TARGET, changeOrigin: true },
      "/status": { target: API_TARGET, changeOrigin: true },
    },
  },
  preview: { port: 5204 },
});
