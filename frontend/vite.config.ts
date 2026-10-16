/**
 * Vite 开发与构建配置
 * 包含 React 插件和后端 API 开发代理
 */
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { Agent as HttpAgent } from "node:http";
import { Agent as HttpsAgent } from "node:https";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_DEV_PROXY_TARGET || "http://127.0.0.1:8000";
  // Windows 本地后端的 Connection: close 路径可间歇重置响应。
  // 开发代理显式保持上游连接，不转发浏览器的关闭连接请求头。
  const agent = backend.startsWith("https:")
    ? new HttpsAgent({ keepAlive: true, maxFreeSockets: 8 })
    : new HttpAgent({ keepAlive: true, maxFreeSockets: 8 });

  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        "/api": {
          target: backend,
          changeOrigin: true,
          agent,
          headers: { connection: "keep-alive" },
        },
      },
    },
  };
});
