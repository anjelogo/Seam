import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL("..", import.meta.url)), "");
  const api = env.API_URL || "http://localhost:8000";
  const gen3d = env.GEN3D_URL || "http://localhost:8001";

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { "@shared": fileURLToPath(new URL("../shared/schema", import.meta.url)) },
    },
    server: {
      port: Number(env.WEB_PORT) || 5273,
      proxy: {
        "/api": { target: api, rewrite: (path) => path.replace(/^\/api/, "") },
        "/gen3d": gen3d,
        "/static": api,
      },
    },
  };
});
