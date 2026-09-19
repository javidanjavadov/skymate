import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
  build: {
    outDir: path.resolve(import.meta.dirname, "../skymate_api/static/web"),
    assetsDir: "app",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    proxy: {
      "/site": "http://127.0.0.1:8000",
      "/v1": "http://127.0.0.1:8000",
    },
  },
})
