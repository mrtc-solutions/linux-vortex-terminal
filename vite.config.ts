import path from "path";
import { fileURLToPath } from "url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), viteSingleFile()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  // Dev/preview ergonomics: listen on all interfaces (sandbox previews),
  // accept the preview host, and proxy /api to a local sidecar so
  // `npm run dev` against `./vortex serve` just works.
  server: {
    host: "0.0.0.0",
    allowedHosts: true,
    proxy: {
      "/api": { target: process.env.VORTEX_DEV_SIDECAR || "http://127.0.0.1:8765", changeOrigin: false },
    },
  },
  preview: {
    host: "0.0.0.0",
    allowedHosts: true,
    proxy: {
      "/api": { target: process.env.VORTEX_DEV_SIDECAR || "http://127.0.0.1:8765", changeOrigin: false },
    },
  },
});
