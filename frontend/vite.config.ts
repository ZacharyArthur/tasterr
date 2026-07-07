/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
	plugins: [react(), tailwindcss()],
	server: {
		proxy: {
			"/api": "http://127.0.0.1:8000",
		},
	},
	test: {
		environment: "jsdom",
		setupFiles: ["./src/test-setup.ts"],
	},
});
