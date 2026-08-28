import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test } from "vitest";
import type { MediaSummary } from "../lib/api";
import { MediaCard } from "./MediaCard";

afterEach(cleanup);

const item = (progress?: number, context?: string): MediaSummary => ({
	id: 1,
	media_type: "movie",
	title: "Top Gun",
	overview: "",
	poster_path: null,
	backdrop_path: null,
	year: 1986,
	vote_average: 7,
	progress_percent: progress,
	context,
});

test("ordinary cards have no progress UI", () => {
	render(
		<MemoryRouter>
			<MediaCard item={item()} />
		</MemoryRouter>,
	);

	expect(screen.queryByRole("progressbar")).toBeNull();
});

test("resume cards expose progress and local episode context accessibly", () => {
	render(
		<MemoryRouter>
			<MediaCard item={item(62, "S2 E3")} />
		</MemoryRouter>,
	);

	const progress = screen.getByRole("progressbar", {
		name: "Top Gun: 62% watched, S2 E3",
	});
	expect(progress.getAttribute("aria-valuenow")).toBe("62");
	expect(progress.getAttribute("aria-valuemin")).toBe("0");
	expect(progress.getAttribute("aria-valuemax")).toBe("100");
	expect(screen.getByText("62% watched")).toBeTruthy();
	expect(screen.getByText("S2 E3")).toBeTruthy();
	expect(screen.getByRole("link", { name: /Top Gun/ }).className).toContain(
		"focus-visible:outline-3",
	);
});
