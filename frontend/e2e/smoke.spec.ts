import { expect, test } from "@playwright/test";

const origin = "http://127.0.0.1:8765";

test("local login, browse, detail, and request use the real backend", async ({
	page,
}) => {
	const unexpectedOrigins = new Set<string>();
	page.on("request", (request) => {
		const requestOrigin = new URL(request.url()).origin;
		if (requestOrigin !== origin) {
			unexpectedOrigins.add(requestOrigin);
		}
	});

	await page.goto("/");
	await page.getByLabel("Email").fill("viewer@example.invalid");
	await page.getByLabel("Password").fill("placeholder-password");
	await page.getByRole("button", { name: "Sign in", exact: true }).click();

	await expect(
		page.getByRole("heading", { name: "Trending Now" }),
	).toBeVisible();
	await page
		.getByRole("link", { name: /Fixture Movie 101/ })
		.first()
		.click();
	await expect(
		page.getByRole("dialog", { name: "Fixture Movie 101" }),
	).toBeVisible();

	await page.getByRole("button", { name: "Request", exact: true }).click();
	await expect(page.getByText("Requested ✓", { exact: true })).toBeVisible();
	await expect.poll(() => [...unexpectedOrigins]).toEqual([]);
});
