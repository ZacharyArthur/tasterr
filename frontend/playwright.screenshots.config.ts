import { defineConfig } from "@playwright/test";
import config from "./playwright.config";

export default defineConfig(config, {
	testMatch: "**/screenshots.capture.ts",
	retries: 0,
	use: {
		baseURL: "http://127.0.0.1:8766",
		colorScheme: "dark",
		contextOptions: { reducedMotion: "reduce" },
	},
	webServer: {
		command:
			"cd ../backend && TASTERR_E2E_PORT=8766 TASTERR_E2E_SCREENSHOTS=1 uv run python scripts/e2e_server.py",
		url: "http://127.0.0.1:8766/api/_e2e/ready",
		reuseExistingServer: false,
		timeout: 60_000,
		stdout: "pipe",
		stderr: "pipe",
	},
});
