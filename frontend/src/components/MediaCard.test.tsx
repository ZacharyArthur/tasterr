import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import type { MediaSummary } from "../lib/api";
import { MediaCard } from "./MediaCard";

const config = vi.hoisted(() => ({
	language: undefined as string | undefined,
}));
vi.mock("../lib/availability", async (importOriginal) => ({
	...(await importOriginal<typeof import("../lib/availability")>()),
	useConfig: () => ({
		data: config.language ? { metadata_language: config.language } : undefined,
	}),
}));

afterEach(() => {
	cleanup();
	config.language = undefined;
});

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

test.each(["es-ES", "en-US", undefined])(
	"marks only TMDB card text with loaded language %s",
	(language) => {
		config.language = language;
		render(
			<MemoryRouter>
				<MediaCard item={item()} />
			</MemoryRouter>,
		);
		for (const title of screen.getAllByText("Top Gun")) {
			expect(title.getAttribute("lang")).toBe(language ?? null);
		}
		expect(screen.getByRole("link").hasAttribute("lang")).toBe(false);
		expect(screen.getByText("1986").hasAttribute("lang")).toBe(false);
	},
);

test("next-up cards show episode context without a progress bar", () => {
	render(
		<MemoryRouter>
			<MediaCard item={item(undefined, "S2 E3")} />
		</MemoryRouter>,
	);

	expect(screen.getByText("S2 E3")).toBeTruthy();
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
