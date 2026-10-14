/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The production build goes straight into the Python package, which serves it.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/speakcheck/web/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"], css: false },
});
