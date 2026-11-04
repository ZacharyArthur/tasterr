import { expect, type Locator, test } from "@playwright/test";

// Synthetic artwork only; no third-party images or household catalog data.
function artwork(id: number, backdrop: boolean): string {
	const hue = (id * 47) % 360;
	const width = backdrop ? 1440 : 500;
	const height = backdrop ? 800 : 750;
	return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 500 750" preserveAspectRatio="xMidYMid slice">
  <defs>
    <linearGradient id="sky" x2="0.8" y2="1"><stop stop-color="hsl(${hue} 65% 32%)"/><stop offset="1" stop-color="#101422"/></linearGradient>
    <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.6" numOctaves="3" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0.12"/></feComponentTransfer><feBlend in="SourceGraphic" mode="soft-light"/></filter>
  </defs>
  <g filter="url(#grain)">
    <path fill="url(#sky)" d="M0 0h500v750H0z"/>
    <circle cx="340" cy="230" r="100" fill="hsl(${hue} 80% 78%)" opacity="0.8"/>
    <path d="M0 460 150 280 340 500 500 340V750H0Z" fill="hsl(${hue} 35% 20%)"/>
    <path d="M0 600 250 410 500 650V750H0Z" fill="#111827"/>
  </g>
  <text x="40" y="64" fill="white" opacity="0.65" font-family="sans-serif" font-size="16" letter-spacing="5">TASTERR DEMO</text>
  <text x="40" y="665" fill="white" font-family="sans-serif" font-weight="700" font-size="36">FIXTURE ${id}</text>
  <text x="40" y="704" fill="white" opacity="0.6" font-family="sans-serif" font-size="16" letter-spacing="3">INVENTED CATALOG</text>
</svg>`;
}

async function frame(heading: Locator): Promise<void> {
	await heading.evaluate((element) =>
		window.scrollTo(
			0,
			element.getBoundingClientRect().top + window.scrollY - 100,
		),
	);
}

test("capture documentation screenshots", async ({ page, baseURL }) => {
	expect(
		await page.evaluate(
			() => matchMedia("(prefers-reduced-motion: reduce)").matches,
		),
	).toBe(true);
	const externalRequests: string[] = [];
	await page.route("**/*", async (route) => {
		const url = new URL(route.request().url());
		const fixture = url.pathname.match(
			/\/fixture-(poster|backdrop)-(\d+)\.svg$/,
		);
		if (url.origin === "https://image.tmdb.org" && fixture) {
			await route.fulfill({
				contentType: "image/svg+xml",
				body: artwork(Number(fixture[2]), fixture[1] === "backdrop"),
			});
		} else if (url.origin === baseURL) {
			await route.continue();
		} else {
			externalRequests.push(url.origin);
			await route.abort();
		}
	});

	await page.goto("/");
	await page.getByRole("button", { name: "Continue with Seerr" }).click();
	await page.getByLabel("Email").fill("viewer@example.invalid");
	await page.getByLabel("Password").fill("placeholder-password");
	await page.getByRole("button", { name: "Sign in", exact: true }).click();
	await expect(
		page.getByRole("heading", { name: "Trending Now" }),
	).toBeVisible();
	await page.getByRole("button", { name: "Skip", exact: true }).click();
	await expect(
		page.getByRole("heading", { name: "Pick a few titles you like" }),
	).toHaveCount(0);
	await page.goto("/account");
	await page.getByRole("button", { name: "Link Trakt" }).click();
	await expect(page.getByText("Fixture Trakt member")).toBeVisible();
	const seeded = await page.request.post("/api/_e2e/screenshots/seed");
	expect(seeded.status()).toBe(204);

	for (const [name, path] of [
		["home", "/"],
		["detail", "/title/movie/101"],
		["search", "/search?q=Fixture"],
		["account", "/account"],
		["household", "/"],
	]) {
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto(path);
		if (name === "account") {
			await expect(page.getByText("Demo Jellyfin member")).toBeVisible();
			await expect(page.getByText("Fixture Trakt member")).toBeVisible();
			await expect(page.getByRole("switch")).toHaveCount(5);
			await expect(
				page.getByRole("switch", {
					name: "Use Plex history for recommendations",
				}),
			).toBeVisible();
			await expect(
				page.getByRole("switch", {
					name: "Use Trakt history for recommendations",
				}),
			).toBeVisible();
		} else if (name === "search") {
			await expect(
				page.getByRole("link", { name: /Fixture Movie 10/ }).first(),
			).toBeVisible();
		}
		if (name === "home") {
			await frame(
				page.getByRole("heading", { name: "Continue Watching", exact: true }),
			);
			await expect(
				page.getByRole("heading", { name: "Recommended for You", exact: true }),
			).toBeVisible();
			await expect(page.getByRole("progressbar")).toHaveCount(4);
		}
		if (name === "detail") {
			await expect(
				page.getByRole("dialog", { name: "Fixture Movie 101" }),
			).toBeVisible();
			await expect(
				page.getByRole("button", { name: "Request", exact: true }),
			).toBeVisible();
			await page
				.getByRole("button", { name: "Request", exact: true })
				.evaluate((button) => button.scrollIntoView({ block: "center" }));
		}
		if (name === "household") {
			const heading = page
				.getByRole("heading", {
					name: "Something for Everyone Tonight",
					exact: true,
				})
				.first();
			await heading.click();
			await page.getByLabel("Demo guest").check();
			await page.getByRole("button", { name: "Find something for us" }).click();
			await expect(
				page
					.getByRole("region", {
						name: "Something for Everyone Tonight",
						exact: true,
					})
					.last()
					.getByRole("link")
					.first(),
			).toBeVisible();
			await frame(heading);
		}
		await expect(page.getByText("Checking…", { exact: true })).toHaveCount(0);
		await page.evaluate(async () => {
			await document.fonts.ready;
			const visible = Array.from(document.images).filter((image) => {
				const rect = image.getBoundingClientRect();
				return (
					rect.top < window.innerHeight &&
					rect.bottom > 0 &&
					rect.left < window.innerWidth &&
					rect.right > 0
				);
			});
			await Promise.all(visible.map((image) => image.decode()));
		});
		await page.mouse.move(0, 0);
		await page.screenshot({
			path: `../docs/screenshots/${name}.jpg`,
			fullPage: name === "account",
			type: "jpeg",
			quality: 96,
			animations: "disabled",
		});
	}
	expect(externalRequests).toEqual([]);
});
