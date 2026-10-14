/// <reference types="vitest" />
import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The production build goes straight into the Python package, which serves it.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: { outDir: "../src/zephvox/web/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"], css: false },
});
