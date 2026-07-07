import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import type { HeroSlide } from "../lib/api";
import { Hero } from "./Hero";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

function slide(id: number, title: string): HeroSlide {
	return {
		item: {
			id,
			media_type: "movie",
			title,
			overview: "",
			poster_path: null,
			backdrop_path: "/b.jpg",
			year: 2020,
			vote_average: 7,
		},
		logo_path: null,
		trailer: null,
		certification: null,
		runtime: null,
		genres: [],
	};
}

function stubMatchMedia(matches: boolean) {
	vi.stubGlobal(
		"matchMedia",
		vi.fn((query: string) => ({
			matches,
			media: query,
			onchange: null,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			addListener: vi.fn(),
			removeListener: vi.fn(),
			dispatchEvent: vi.fn(),
		})),
	);
}

function renderHero() {
	render(
		<MemoryRouter>
			<Hero slides={[slide(1, "First"), slide(2, "Second")]} />
		</MemoryRouter>,
	);
}

test("rotates the hero when motion is allowed", () => {
	vi.useFakeTimers();
	stubMatchMedia(false);
	renderHero();
	expect(screen.getByRole("heading", { name: "First" })).toBeTruthy();
	act(() => {
		vi.advanceTimersByTime(7000);
	});
	expect(screen.getByRole("heading", { name: "Second" })).toBeTruthy();
});

test("does not rotate under reduced motion", () => {
	vi.useFakeTimers();
	stubMatchMedia(true);
	renderHero();
	act(() => {
		vi.advanceTimersByTime(21000);
	});
	expect(screen.getByRole("heading", { name: "First" })).toBeTruthy();
	expect(screen.queryByRole("heading", { name: "Second" })).toBeNull();
});
