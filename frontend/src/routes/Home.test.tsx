import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { Home } from "./Home";
import { Settings } from "./Settings";

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

test.each([
	"completed-blend",
	"pending-blend",
	"initial-feed",
])("save completion clears stale discovery obtained after leaving Settings, mode=%s", async (mode) => {
	const pendingBlend = mode === "pending-blend";
	const pendingFeed = mode === "initial-feed";
	vi.stubGlobal("IntersectionObserver", FiringIntersectionObserver);
	let resolveHome!: (response: Response) => void;
	const homeResponse = new Promise<Response>((resolve) => {
		resolveHome = resolve;
	});
	let resolveRails!: (response: Response) => void;
	const railsResponse = new Promise<Response>((resolve) => {
		resolveRails = resolve;
	});
	let resolveSave!: (response: Response) => void;
	const saveResponse = new Promise<Response>((resolve) => {
		resolveSave = resolve;
	});
	let resolveBlend!: (response: Response) => void;
	const blendResponse = new Promise<Response>((resolve) => {
		resolveBlend = resolve;
	});
	const settings = {
		settings: {
			region: "US",
			service_ids: [],
			disabled_rail_types: [],
			hide_library_items: false,
			excluded_service_ids: [],
			appearance: { theme: "dark", accent: "crimson" },
		},
		rail_types: [],
	};
	let homeReads = 0;
	let railsReads = 0;
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = String(input);
			if (url === "/api/v1/settings")
				return init?.method === "PUT" ? saveResponse : jsonResponse(settings);
			if (url === "/api/v1/regions")
				return jsonResponse({
					regions: [{ code: "US", name: "United States" }],
				});
			if (url.startsWith("/api/v1/services"))
				return jsonResponse({ region: "US", services: [] });
			if (url === "/api/v1/home") {
				homeReads++;
				if (pendingFeed && homeReads === 1) return homeResponse;
				return jsonResponse({
					hero: [],
					rails: [rail("trending", "Trending Now")],
				});
			}
			if (url.startsWith("/api/v1/rails")) {
				railsReads++;
				if (pendingFeed && railsReads === 1) return railsResponse;
				return jsonResponse({ rails: [], next_cursor: null });
			}
			if (url === "/api/v1/taste-onboarding")
				return jsonResponse({ state: "done" });
			if (url.endsWith("household-members"))
				return jsonResponse(
					[1, 2].map((id) => ({
						id,
						display_name: `Viewer ${id}`,
						avatar_url: null,
						has_taste_signals: true,
					})),
				);
			if (url.endsWith("household-blend"))
				return pendingBlend
					? blendResponse
					: jsonResponse({
							...rail("household-blend", "Something for Everyone Tonight"),
							items: [card(901), card(902), card(903), card(904)],
						});
			if (url === "/api/v1/availability" || url === "/api/v1/config")
				return jsonResponse({});
			throw new Error(`unexpected fixture route: ${url}`);
		}),
	);
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	queryClient.setQueryData(["auth", "me"], {
		id: 1,
		display_name: "Admin",
		avatar_url: null,
		is_admin: true,
	});
	render(
		<QueryClientProvider client={queryClient}>
			<MemoryRouter initialEntries={["/settings"]}>
				<Link to="/">Return Home</Link>
				<Routes>
					<Route path="/settings" element={<Settings />} />
					<Route path="/" element={<Home />} />
				</Routes>
			</MemoryRouter>
		</QueryClientProvider>,
	);
	fireEvent.click(
		await screen.findByLabelText("Hide titles already in the library"),
	);
	fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
	await screen.findByRole("button", { name: "Saving…" });
	fireEvent.click(screen.getByRole("link", { name: "Return Home" }));
	if (pendingFeed) {
		await waitFor(() => expect(homeReads).toBe(1));
		await waitFor(() => expect(railsReads).toBe(1));
		expect(queryClient.getQueryData(["home"])).toBeUndefined();
	} else {
		fireEvent.click(
			await screen.findByRole("heading", {
				name: "Something for Everyone Tonight",
			}),
		);
		fireEvent.click(await screen.findByRole("checkbox", { name: "Viewer 2" }));
		fireEvent.click(
			screen.getByRole("button", { name: "Find something for us" }),
		);
		if (pendingBlend)
			await screen.findByRole("button", { name: "Finding a shared pick…" });
		else await screen.findAllByText("T901");
	}
	resolveSave(
		jsonResponse({
			...settings,
			settings: { ...settings.settings, hide_library_items: true },
		}),
	);
	await waitFor(() => expect(homeReads).toBe(2));
	await screen.findByText("Trending Now");
	if (pendingFeed) {
		await waitFor(() => expect(railsReads).toBe(2));
		const oldHome = {
			hero: [],
			rails: [{ ...rail("old-home", "Old Home"), items: [card(901)] }],
		};
		const oldRails = {
			rails: [{ ...rail("old-rails", "Old Rails"), items: [card(902)] }],
			next_cursor: null,
		};
		const homeJson = vi.fn(async () => oldHome);
		const railsJson = vi.fn(async () => oldRails);
		resolveHome({ ...jsonResponse(oldHome), json: homeJson } as Response);
		resolveRails({ ...jsonResponse(oldRails), json: railsJson } as Response);
		await waitFor(() => expect(homeJson).toHaveBeenCalled());
		await waitFor(() => expect(railsJson).toHaveBeenCalled());
		expect(queryClient.getQueryData(["home"])).toEqual({
			hero: [],
			rails: [rail("trending", "Trending Now")],
		});
		expect(queryClient.getQueryData(["rails"])).toEqual({
			pages: [{ rails: [], next_cursor: null }],
			pageParams: [0],
		});
		expect(queryClient.getQueryState(["home"])?.isInvalidated).toBe(false);
		expect(screen.queryByText("T902")).toBeNull();
	}
	await waitFor(() =>
		expect(
			(screen.getByRole("checkbox", { name: "Viewer 2" }) as HTMLInputElement)
				.checked,
		).toBe(false),
	);
	expect(screen.queryByText("T901")).toBeNull();
	if (pendingBlend) {
		resolveBlend(
			jsonResponse({
				...rail("household-blend", "Something for Everyone Tonight"),
				items: [card(901), card(902), card(903), card(904)],
			}),
		);
		await waitFor(() =>
			expect(
				queryClient
					.getMutationCache()
					.getAll()
					.some((mutation) => mutation.state.status === "pending"),
			).toBe(false),
		);
		expect(screen.queryByText("T901")).toBeNull();
	}
});
