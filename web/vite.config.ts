import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the browser calls /api/... on this server, and Vite forwards it to the Python
// API. Same origin, so no CORS setup is needed until the app is deployed (P2).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
