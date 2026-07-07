import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { Home } from "./Home";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

function jsonResponse(body: unknown): Response {
	return { ok: true, status: 200, json: async () => body } as Response;
}

function card(id: number) {
	return {
		id,
		media_type: "movie",
		title: `T${id}`,
		overview: "",
		poster_path: null,
		backdrop_path: "/b.jpg",
		year: 2020,
		vote_average: 7,
	};
}

function rail(id: string, title: string) {
	return {
		id,
		title,
		kind: "standard",
		items: [card(1), card(2), card(3), card(4)],
	};
}

// An IntersectionObserver that fires immediately on observe, so the sentinel
// drives fetchNextPage in the test.
class FiringIntersectionObserver {
	root = null;
	rootMargin = "";
	thresholds: readonly number[] = [];
	private cb: IntersectionObserverCallback;
	constructor(cb: IntersectionObserverCallback) {
		this.cb = cb;
	}
	observe() {
		this.cb(
			[{ isIntersecting: true } as IntersectionObserverEntry],
			this as unknown as IntersectionObserver,
		);
	}
	unobserve() {}
	disconnect() {}
	takeRecords(): IntersectionObserverEntry[] {
		return [];
	}
}

function renderHome() {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={queryClient}>
			<MemoryRouter>
				<Home />
			</MemoryRouter>
		</QueryClientProvider>,
	);
}

test("renders the hero and rails, then loads more via the sentinel", async () => {
	vi.stubGlobal("IntersectionObserver", FiringIntersectionObserver);
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url === "/api/v1/home") {
				return jsonResponse({
					hero: [
						{
							item: card(1),
							logo_path: null,
							trailer: null,
							certification: null,
							runtime: null,
							genres: [],
						},
					],
					rails: [rail("trending", "Trending Now")],
				});
			}
			if (url === "/api/v1/rails?cursor=0") {
				return jsonResponse({
					rails: [rail("top-rated-movie", "Top Rated Movies")],
					next_cursor: 4,
				});
			}
			return jsonResponse({
				rails: [rail("decade-2020", "2020s")],
				next_cursor: null,
			});
		}),
	);

	renderHome();

	expect(await screen.findByText("Trending Now")).toBeTruthy();
	expect(await screen.findByText("Top Rated Movies")).toBeTruthy(); // auto-loaded first page
	expect(await screen.findByText("2020s")).toBeTruthy(); // sentinel-triggered next page
});
