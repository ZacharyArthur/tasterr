import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router";
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

function renderHome(user?: {
	id: number;
	display_name: string;
	avatar_url: null;
	is_admin: boolean;
}) {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	if (user) queryClient.setQueryData(["auth", "me"], user);
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
	let resolveHome!: (response: Response) => void;
	const homeResponse = new Promise<Response>((resolve) => {
		resolveHome = resolve;
	});
	const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		if (url === "/api/v1/home") {
			return homeResponse;
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
	});
	vi.stubGlobal("fetch", fetchMock);

	renderHome();
	await waitFor(() =>
		expect(
			fetchMock.mock.calls.some(
				([input]) => String(input) === "/api/v1/rails?cursor=0",
			),
		).toBe(true),
	);
	resolveHome(
		jsonResponse({
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
		}),
	);

	expect(await screen.findByText("Trending Now")).toBeTruthy();
	expect(await screen.findByText("Top Rated Movies")).toBeTruthy(); // auto-loaded first page
	expect(await screen.findByText("2020s")).toBeTruthy(); // sentinel-triggered next page
});

test("all-disabled empty state gives only admins a Settings recovery link", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL) => {
			if (String(input) === "/api/v1/home")
				return jsonResponse({ hero: [], rails: [] });
			return jsonResponse({ rails: [], next_cursor: null });
		}),
	);
	renderHome({
		id: 1,
		display_name: "Admin",
		avatar_url: null,
		is_admin: true,
	});
	expect(await screen.findByText("Your home feed is empty")).toBeTruthy();
	expect(screen.getByRole("link", { name: "Open Settings" })).toBeTruthy();

	cleanup();
	renderHome({
		id: 2,
		display_name: "Viewer",
		avatar_url: null,
		is_admin: false,
	});
	expect(await screen.findByText("Your home feed is empty")).toBeTruthy();
	expect(screen.queryByRole("link", { name: "Open Settings" })).toBeNull();
});

test("household work does not block Home and its rail may repeat a Home title", async () => {
	vi.stubGlobal("IntersectionObserver", FiringIntersectionObserver);
	let resolveMembers!: (response: Response) => void;
	const membersResponse = new Promise<Response>((resolve) => {
		resolveMembers = resolve;
	});
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url === "/api/v1/home") {
				return jsonResponse({
					hero: [],
					rails: [rail("trending", "Trending Now")],
				});
			}
			if (url === "/api/v1/rails?cursor=0") {
				return jsonResponse({ rails: [], next_cursor: null });
			}
			if (url === "/api/v1/taste-onboarding") {
				return jsonResponse({ state: "done" });
			}
			if (url === "/api/v1/recommendations/household-members") {
				return membersResponse;
			}
			if (url === "/api/v1/recommendations/household-blend") {
				return jsonResponse({
					id: "household-blend",
					title: "Something for Everyone Tonight",
					kind: "standard",
					items: [card(1), card(5), card(6), card(7)],
				});
			}
			if (url === "/api/v1/availability") return jsonResponse({});
			throw new Error(`unexpected fetch: ${url}`);
		}),
	);
	renderHome({
		id: 1,
		display_name: "Viewer 1",
		avatar_url: null,
		is_admin: false,
	});

	expect(await screen.findByText("Trending Now")).toBeTruthy();
	expect(screen.queryByRole("checkbox", { name: "Viewer 2" })).toBeNull();
	resolveMembers(
		jsonResponse([
			{
				id: 1,
				display_name: "Viewer 1",
				avatar_url: null,
				has_taste_signals: true,
			},
			{
				id: 2,
				display_name: "Viewer 2",
				avatar_url: null,
				has_taste_signals: true,
			},
		]),
	);
	fireEvent.click(
		await screen.findByRole("heading", {
			name: "Something for Everyone Tonight",
		}),
	);
	fireEvent.click(await screen.findByRole("checkbox", { name: "Viewer 2" }));
	fireEvent.click(
		screen.getByRole("button", { name: "Find something for us" }),
	);

	await screen.findByRole("region", { name: "Something for Everyone Tonight" });
	expect(
		screen
			.getAllByRole("link")
			.filter((link) => link.getAttribute("href") === "/title/movie/1"),
	).toHaveLength(2);
});
