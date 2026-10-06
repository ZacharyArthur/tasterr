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
	await page.getByRole("button", { name: "Request 4K", exact: true }).click();
	await expect(page.getByText("Requested ✓", { exact: true })).toBeVisible();
	await expect(
		page.getByRole("button", { name: /^Request( 4K)?$/ }),
	).toHaveCount(0);
	await expect.poll(() => [...unexpectedOrigins]).toEqual([]);
});

test("missing 4K upgrade uses Seerr defaults and keeps standard available", async ({
	page,
}) => {
	await page.goto("/");
	await page.getByLabel("Email").fill("viewer@example.invalid");
	await page.getByLabel("Password").fill("placeholder-password");
	await page.getByRole("button", { name: "Sign in", exact: true }).click();
	await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
	await page.goto("/title/movie/102");
	await expect(
		page.getByRole("dialog").getByText("Available", { exact: true }),
	).toBeVisible();
	const sent = page.waitForRequest(
		(request) =>
			request.url().endsWith("/api/v1/request") && request.method() === "POST",
	);
	await page.getByRole("button", { name: "Request 4K", exact: true }).click();
	expect((await sent).postDataJSON()).toEqual({
		media_type: "movie",
		tmdb_id: 102,
		is_4k: true,
	});
	await expect(page.getByText("Requested ✓", { exact: true })).toBeVisible();
	await expect(
		page.getByRole("dialog").getByText("Available", { exact: true }),
	).toBeVisible();
});

test("phone advanced 4K selection supports cancellation and keyboard confirmation", async ({
	page,
}) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto("/");
	await page.getByLabel("Email").fill("viewer@example.invalid");
	await page.getByLabel("Password").fill("placeholder-password");
	await page.getByRole("button", { name: "Sign in", exact: true }).click();
	await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
	await page.goto("/title/movie/104");
	await page.getByRole("button", { name: "Choose destination" }).click();
	await page
		.getByRole("combobox", { name: "Server", exact: true })
		.selectOption("1");
	await page.getByRole("button", { name: "Cancel", exact: true }).click();
	await expect(
		page.getByRole("combobox", { name: "Server", exact: true }),
	).toHaveCount(0);
	await page.getByRole("button", { name: "Choose destination" }).click();
	await page
		.getByRole("combobox", { name: "Server", exact: true })
		.selectOption("1");
	await page
		.getByRole("button", { name: "Confirm request", exact: true })
		.scrollIntoViewIfNeeded();
	await page.screenshot({ path: "test-results/request-picker-mobile.png" });
	const sent = page.waitForRequest(
		(request) =>
			request.url().endsWith("/api/v1/request") && request.method() === "POST",
	);
	await page
		.getByRole("button", { name: "Confirm request", exact: true })
		.focus();
	await page.keyboard.press("Enter");
	expect((await sent).postDataJSON()).toEqual({
		media_type: "movie",
		tmdb_id: 104,
		is_4k: true,
		server_id: 1,
		profile_id: 7,
		root_folder: "/4k",
	});
	await expect(page.getByText("Requested ✓", { exact: true })).toBeVisible();
	expect(
		await page.evaluate(
			() => document.documentElement.scrollWidth <= window.innerWidth,
		),
	).toBe(true);
});

test("4K TV request keeps the whole-series contract", async ({ page }) => {
	await page.goto("/");
	await page.getByLabel("Email").fill("viewer@example.invalid");
	await page.getByLabel("Password").fill("placeholder-password");
	await page.getByRole("button", { name: "Sign in", exact: true }).click();
	await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
	await page.goto("/title/tv/105");
	await page
		.getByRole("combobox", { name: "Quality", exact: true })
		.selectOption("4k");
	const sent = page.waitForRequest(
		(request) =>
			request.url().endsWith("/api/v1/request") && request.method() === "POST",
	);
	await page.getByRole("button", { name: "Request 4K", exact: true }).click();
	expect((await sent).postDataJSON()).toEqual({
		media_type: "tv",
		tmdb_id: 105,
		is_4k: true,
	});
	await expect(page.getByText("Requested ✓", { exact: true })).toBeVisible();
});

test("phone TV season dialog sends only the chosen seasons", async ({
	page,
}) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto("/");
	await page.getByLabel("Email").fill("viewer@example.invalid");
	await page.getByLabel("Password").fill("placeholder-password");
	await page.getByRole("button", { name: "Sign in", exact: true }).click();
	await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
	await page.goto("/title/tv/106");
	await page.getByRole("button", { name: "Request", exact: true }).click();
	const picker = page.getByRole("dialog", { name: "Choose seasons" });
	await expect(picker).toBeVisible();
	await expect(
		picker.getByRole("switch", { name: /Specials/ }),
	).toHaveAttribute("aria-checked", "false");
	await page.screenshot({
		path: "test-results/season-picker-default.png",
		animations: "disabled",
	});
	await picker.getByRole("switch", { name: /Season 1/ }).click();
	await picker.getByRole("switch", { name: /Specials/ }).click();
	await page.screenshot({
		path: "test-results/season-picker-chosen.png",
		animations: "disabled",
	});
	await picker.getByRole("button", { name: "Cancel", exact: true }).click();
	await expect(picker).toHaveCount(0);
	await expect(
		page.getByRole("dialog", { name: "Fixture Show 106" }),
	).toBeVisible();
	const request = page.getByRole("button", { name: "Request", exact: true });
	await request.click();
	await page.keyboard.press("Escape");
	await expect(picker).toHaveCount(0);
	await expect(
		page.getByRole("dialog", { name: "Fixture Show 106" }),
	).toBeVisible();
	await expect(request).toBeFocused();
	await request.click();
	await picker.getByRole("switch", { name: /Season 1/ }).click();
	const sent = page.waitForRequest(
		(request) =>
			request.url().endsWith("/api/v1/request") && request.method() === "POST",
	);
	await picker.getByRole("button", { name: "OK", exact: true }).click();
	expect((await sent).postDataJSON()).toEqual({
		media_type: "tv",
		tmdb_id: 106,
		seasons: [2, 3],
	});
	await expect(page.getByText("Requested ✓", { exact: true })).toBeVisible();
	expect(
		await page.evaluate(
			() => document.documentElement.scrollWidth <= window.innerWidth,
		),
	).toBe(true);
});
