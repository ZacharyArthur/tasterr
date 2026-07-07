import { expect, test } from "vitest";
import { backdropUrl, posterUrl, providerLogoUrl } from "./images";

test("builds sized image urls from a path", () => {
	expect(posterUrl("/p.jpg", "w500")).toBe(
		"https://image.tmdb.org/t/p/w500/p.jpg",
	);
	expect(backdropUrl("/b.jpg")).toBe("https://image.tmdb.org/t/p/w1280/b.jpg");
	expect(providerLogoUrl("/n.png")).toBe(
		"https://image.tmdb.org/t/p/w92/n.png",
	);
});

test("returns null for a missing path", () => {
	expect(posterUrl(null)).toBeNull();
	expect(backdropUrl(undefined)).toBeNull();
});
