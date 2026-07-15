import { defineConfig, devices } from "@playwright/test";

const origin = "http://127.0.0.1:8765";

export default defineConfig({
	testDir: "./e2e",
	fullyParallel: false,
	workers: 1,
	retries: process.env.CI ? 1 : 0,
	reporter: [
		["list"],
		["html", { open: "never", outputFolder: "playwright-report" }],
	],
	outputDir: "test-results",
	use: {
		baseURL: origin,
		trace: "off",
		screenshot: "only-on-failure",
		video: "off",
	},
	projects: [
		{
			name: "chromium",
			use: { ...devices["Desktop Chrome"] },
		},
	],
	webServer: {
		command: "cd ../backend && uv run python scripts/e2e_server.py",
		url: `${origin}/api/_e2e/ready`,
		reuseExistingServer: false,
		timeout: 60_000,
		stdout: "pipe",
		stderr: "pipe",
	},
});
