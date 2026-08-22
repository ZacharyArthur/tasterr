import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { MediaSummary } from "../lib/api";
import { TastePicker } from "./TastePicker";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

function item(id: number): MediaSummary {
	return {
		id,
		media_type: id % 2 ? "movie" : "tv",
		title: `Title ${id}`,
		overview: "",
		poster_path: null,
		backdrop_path: null,
		year: 2020,
		vote_average: 7,
	};
}

function jsonResponse(body: unknown): Response {
	return { ok: true, status: 200, json: async () => body } as Response;
}

function renderPicker(items: MediaSummary[], userId = 1) {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	const view = (nextItems: MediaSummary[], nextUserId: number) => (
		<QueryClientProvider client={queryClient}>
			<a href="/search">Browse search</a>
			<TastePicker items={nextItems} userId={nextUserId} />
		</QueryClientProvider>
	);
	const result = render(view(items, userId));
	return {
		...result,
		rerenderPicker: (nextItems: MediaSummary[], nextUserId = userId) =>
			result.rerender(view(nextItems, nextUserId)),
	};
}

test("shows at most 12 unique feed titles without blocking browse controls", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(async () => jsonResponse({ state: "show" })),
	);
	renderPicker([
		item(1),
		item(1),
		...Array.from({ length: 13 }, (_, i) => item(i + 2)),
	]);

	expect(await screen.findByText("Pick a few titles you like")).toBeTruthy();
	expect(document.querySelectorAll("button[aria-pressed]")).toHaveLength(12);
	expect(screen.getByRole("link", { name: "Browse search" })).toBeTruthy();
	expect(screen.queryByRole("button", { name: "Choose Title 14" })).toBeNull();
});

test("selection posts typed title keys and disappears after success", async () => {
	const posts: unknown[] = [];
	vi.stubGlobal(
		"fetch",
		vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
			if (init?.method === "POST") {
				posts.push(JSON.parse(String(init.body)));
				return jsonResponse({ recorded_signals: 1 });
			}
			return jsonResponse({ state: "show" });
		}),
	);
	renderPicker([item(1), item(2)]);

	const choice = await screen.findByRole("button", { name: "Choose Title 1" });
	choice.focus();
	expect(document.activeElement).toBe(choice);
	fireEvent.click(choice);
	expect(
		screen
			.getByRole("button", { name: "Remove Title 1" })
			.getAttribute("aria-pressed"),
	).toBe("true");
	fireEvent.click(screen.getByRole("button", { name: "Use these picks" }));

	await waitFor(() =>
		expect(posts).toEqual([
			{ selections: [{ media_type: "movie", tmdb_id: 1 }] },
		]),
	);
	expect(screen.queryByText("Pick a few titles you like")).toBeNull();
});

test("selected title keys survive a feed candidate refresh", async () => {
	const posts: unknown[] = [];
	vi.stubGlobal(
		"fetch",
		vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
			if (init?.method === "POST") {
				posts.push(JSON.parse(String(init.body)));
				return jsonResponse({ recorded_signals: 1 });
			}
			return jsonResponse({ state: "show" });
		}),
	);
	const view = renderPicker([item(1), item(2)]);

	fireEvent.click(
		await screen.findByRole("button", { name: "Choose Title 1" }),
	);
	view.rerenderPicker([item(2), item(3)]);
	expect(screen.queryByRole("button", { name: "Remove Title 1" })).toBeNull();
	fireEvent.click(screen.getByRole("button", { name: "Use these picks" }));

	await waitFor(() =>
		expect(posts).toEqual([
			{ selections: [{ media_type: "movie", tmdb_id: 1 }] },
		]),
	);
});

test("retained selections can be cleared after reaching 12 across a feed refresh", async () => {
	const posts: unknown[] = [];
	vi.stubGlobal(
		"fetch",
		vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
			if (init?.method === "POST") {
				posts.push(JSON.parse(String(init.body)));
				return jsonResponse({ recorded_signals: 12 });
			}
			return jsonResponse({ state: "show" });
		}),
	);
	const firstCandidates = Array.from({ length: 12 }, (_, index) =>
		item(index + 1),
	);
	const view = renderPicker(firstCandidates);
	await screen.findByText("Pick a few titles you like");
	for (const candidate of firstCandidates) {
		fireEvent.click(
			screen.getByRole("button", { name: `Choose ${candidate.title}` }),
		);
	}

	view.rerenderPicker(
		Array.from({ length: 12 }, (_, index) => item(index + 13)),
	);
	const extra = screen.getByRole("button", { name: "Choose Title 13" });
	expect(extra.getAttribute("aria-disabled")).toBe("true");
	extra.focus();
	expect(document.activeElement).toBe(extra);
	fireEvent.click(extra);
	expect(extra.getAttribute("aria-pressed")).toBe("false");

	const clear = screen.getByRole("button", { name: "Clear picks" });
	clear.focus();
	expect(document.activeElement).toBe(clear);
	fireEvent.click(clear);
	expect(extra.getAttribute("aria-disabled")).toBe("false");
	fireEvent.click(extra);
	expect(extra.getAttribute("aria-pressed")).toBe("true");
	fireEvent.click(screen.getByRole("button", { name: "Use these picks" }));

	await waitFor(() => expect(posts).toHaveLength(1));
	const submission = posts[0] as { selections: { tmdb_id: number }[] };
	expect(submission.selections).toEqual([{ media_type: "movie", tmdb_id: 13 }]);
});

test("submission failures are announced and leave the picker usable", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
			if (init?.method === "POST") {
				return {
					ok: false,
					status: 500,
					json: async () => ({ detail: "failed" }),
				} as Response;
			}
			return jsonResponse({ state: "show" });
		}),
	);
	renderPicker([item(1)]);

	fireEvent.click(
		await screen.findByRole("button", { name: "Choose Title 1" }),
	);
	fireEvent.click(screen.getByRole("button", { name: "Use these picks" }));

	const alert = await screen.findByRole("alert");
	expect(alert.textContent).toContain("Couldn't save your choices");
	expect(screen.getByRole("link", { name: "Browse search" })).toBeTruthy();
	expect(screen.getByRole("button", { name: "Remove Title 1" })).toBeTruthy();
});

test("Skip dismisses with an empty selection", async () => {
	const posts: unknown[] = [];
	vi.stubGlobal(
		"fetch",
		vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
			if (init?.method === "POST") {
				posts.push(JSON.parse(String(init.body)));
				return jsonResponse({ recorded_signals: 0 });
			}
			return jsonResponse({ state: "show" });
		}),
	);
	renderPicker([item(1)]);

	fireEvent.click(await screen.findByRole("button", { name: "Skip" }));
	await waitFor(() => expect(posts).toEqual([{ selections: [] }]));
	expect(screen.queryByText("Pick a few titles you like")).toBeNull();
});

test("pending state polls until cold-start seeding finishes", async () => {
	let reads = 0;
	vi.stubGlobal(
		"fetch",
		vi.fn(async () => {
			reads += 1;
			return jsonResponse({ state: reads === 1 ? "pending" : "show" });
		}),
	);
	renderPicker([item(1)]);

	expect(screen.queryByText("Pick a few titles you like")).toBeNull();
	expect(
		await screen.findByText(
			"Pick a few titles you like",
			{},
			{ timeout: 1500 },
		),
	).toBeTruthy();
	expect(reads).toBeGreaterThanOrEqual(2);
});

test("polling stops when a pending-state refresh fails", async () => {
	let reads = 0;
	vi.stubGlobal(
		"fetch",
		vi.fn(async () => {
			reads += 1;
			if (reads === 1) return jsonResponse({ state: "pending" });
			throw new TypeError("offline");
		}),
	);
	renderPicker([item(1)]);

	await waitFor(() => expect(reads).toBe(2), { timeout: 1500 });
	await new Promise((resolve) => window.setTimeout(resolve, 700));
	expect(reads).toBe(2);
	expect(screen.queryByText("Pick a few titles you like")).toBeNull();
});

test("onboarding cache state is scoped to the current user", async () => {
	let reads = 0;
	vi.stubGlobal(
		"fetch",
		vi.fn(async () => {
			reads += 1;
			return jsonResponse({ state: reads === 1 ? "show" : "done" });
		}),
	);
	const view = renderPicker([item(1)], 101);

	expect(await screen.findByText("Pick a few titles you like")).toBeTruthy();
	view.rerenderPicker([item(1)], 202);
	expect(screen.queryByText("Pick a few titles you like")).toBeNull();
	await waitFor(() => expect(reads).toBe(2));
	expect(screen.queryByText("Pick a few titles you like")).toBeNull();
});

test("status failure and an empty candidate list render nothing", async () => {
	const fetchMock = vi.fn(async () => {
		throw new TypeError("offline");
	});
	vi.stubGlobal("fetch", fetchMock);
	renderPicker([item(1)]);
	await waitFor(() => expect(fetchMock).toHaveBeenCalled());
	expect(screen.queryByText("Pick a few titles you like")).toBeNull();

	cleanup();
	vi.stubGlobal(
		"fetch",
		vi.fn(async () => jsonResponse({ state: "show" })),
	);
	renderPicker([]);
	await waitFor(() => expect(fetch).toHaveBeenCalled());
	expect(screen.queryByText("Pick a few titles you like")).toBeNull();
});
