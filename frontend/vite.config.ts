import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
    plugins: [react(), tailwindcss()],
    resolve: {
        alias: { "@": path.resolve(__dirname, "src") },
        extensions: [".mjs", ".mts", ".ts", ".tsx", ".js", ".jsx", ".json"],
    },
    server: {
        host: "0.0.0.0",
        port: 5173,
        proxy: {
            "/api": {
                target: "http://127.0.0.1:1241",
                changeOrigin: true,
            },
            // skill.md 由后端动态渲染（替换 {{BASE_URL}}），代理时保留原始 Host，
            // 让文档中的 API 地址与当前访问来源一致（如 localhost:5173）。
            "/skill.md": {
                target: "http://127.0.0.1:1241",
                changeOrigin: false,
            },
        },
    },
    build: {
        outDir: "dist",
        emptyOutDir: true,
    },
});
