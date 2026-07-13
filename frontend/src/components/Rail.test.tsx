import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import type { Rail as RailData } from "../lib/api";
import { Rail } from "./Rail";

afterEach(() => {
	cleanup();
	vi.restoreAllMocks();
});

const item = (id: number, title: string) => ({
	id,
	media_type: "movie" as const,
	title,
	overview: "",
	poster_path: null,
	backdrop_path: null,
	year: 2020,
	vote_average: 7,
});
const RAIL: RailData = {
	id: "popular",
	title: "Popular",
	kind: "standard",
	items: [item(1, "One"), item(2, "Two"), item(3, "Three")],
};

test("rail is labelled and Arrow keys move card focus without leaving endpoints", () => {
	const scrollIntoView = vi.fn();
	HTMLElement.prototype.scrollIntoView = scrollIntoView;
	render(
		<MemoryRouter>
			<Rail rail={RAIL} />
		</MemoryRouter>,
	);
	screen.getByRole("region", { name: "Popular" });
	const cards = screen.getAllByRole("link");
	cards[0].focus();
	fireEvent.keyDown(cards[0], { key: "ArrowRight" });
	expect(document.activeElement).toBe(cards[1]);
	fireEvent.keyDown(cards[1], { key: "ArrowLeft" });
	expect(document.activeElement).toBe(cards[0]);
	fireEvent.keyDown(cards[0], { key: "ArrowLeft" });
	expect(document.activeElement).toBe(cards[0]);
	expect(cards[0].className).toContain("focus-visible:outline");
	expect(scrollIntoView).toHaveBeenCalled();
});

test("reduced motion uses instant programmatic scrolling", () => {
	const scrollIntoView = vi.fn();
	HTMLElement.prototype.scrollIntoView = scrollIntoView;
	vi.spyOn(window, "matchMedia").mockReturnValue({
		matches: true,
	} as MediaQueryList);
	render(
		<MemoryRouter>
			<Rail rail={RAIL} />
		</MemoryRouter>,
	);
	const cards = screen.getAllByRole("link");
	cards[0].focus();
	fireEvent.keyDown(cards[0], { key: "ArrowRight" });
	expect(scrollIntoView).toHaveBeenCalledWith(
		expect.objectContaining({ behavior: "auto" }),
	);
});
