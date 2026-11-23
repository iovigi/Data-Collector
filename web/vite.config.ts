import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Build-time only: produces a static SPA in dist/ that the Python app serves under IIS.
// No Node.js process runs in production.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, ".") },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    assetsDir: "assets",
    target: "es2022",
  },
  server: {
    // Local development: run the Python app (dc-api / IIS) and proxy API calls to it.
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
