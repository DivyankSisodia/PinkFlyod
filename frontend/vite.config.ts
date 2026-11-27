import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

// Development only: the Vite server (17861) forwards API and WebSocket calls to the app (17860).
// In normal use the app serves the built files from frontend/dist itself.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 17861,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:17860", changeOrigin: true, ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  test: { environment: "node" },
} as never)
