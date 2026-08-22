import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import type { ComponentProps } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { DetailModal } from "./DetailModal";
import { MediaCard } from "./MediaCard";

afterEach(() => {
	cleanup();
	document.body.style.overflow = "";
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

const DETAIL = {
	id: 42,
	media_type: "movie",
	title: "Deep Movie",
	overview: "An overview.",
	poster_path: null,
	backdrop_path: "/b.jpg",
	year: 2020,
	vote_average: 7,
	tagline: "A tagline",
	external_url: "https://www.themoviedb.org/movie/42",
	genres: [{ id: 18, name: "Drama" }],
	runtime: 120,
	release_date: "2020-01-01",
	certification: "PG-13",
	logo_path: null,
	trailer: {
		key: "abc123",
		site: "YouTube",
		type: "Trailer",
		name: "T",
		official: true,
	},
	cast: [{ id: 9, name: "Actor One", role: "Hero", profile_path: null }],
	crew: [],
	watch: {
		flatrate: [{ provider_id: 8, name: "Netflix", logo_path: null }],
		rent: [],
		buy: [],
		free: [],
	},
	recommendations: [],
	similar: [],
	seasons: [],
	number_of_seasons: null,
};

function summary(id: number, title: string) {
	return {
		id,
		media_type: "movie" as const,
		title,
		overview: "",
		poster_path: null,
		backdrop_path: null,
		year: 2021,
		vote_average: 6,
	};
}

function renderModal(
	initialEntries: ComponentProps<typeof MemoryRouter>["initialEntries"] = [
		"/title/movie/42",
	],
) {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	return render(
		<QueryClientProvider client={queryClient}>
			<MemoryRouter initialEntries={initialEntries}>
				<Routes>
					<Route path="/title/:type/:id" element={<DetailModal />} />
					<Route
						path="/"
						element={<MediaCard item={summary(42, "Deep Movie")} />}
					/>
				</Routes>
			</MemoryRouter>
		</QueryClientProvider>,
	);
}

test("renders the title detail sections", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(
			async () =>
				({ ok: true, status: 200, json: async () => DETAIL }) as Response,
		),
	);
	renderModal();

	expect(
		await screen.findByRole("heading", { name: "Deep Movie" }),
	).toBeTruthy();
	expect(screen.getByText("An overview.")).toBeTruthy();
	expect(screen.getByText("Where & how to watch")).toBeTruthy();
	expect(screen.getByText("Netflix")).toBeTruthy();
	expect(screen.getByText("Actor One")).toBeTruthy();
	expect(screen.getByRole("button", { name: "Close" })).toBeTruthy();
	const external = screen.getByRole("link", {
		name: "View on TMDB (opens in a new tab)",
	});
	expect(external.getAttribute("href")).toBe(
		"https://www.themoviedb.org/movie/42",
	);
	expect(external.getAttribute("target")).toBe("_blank");
	expect(external.getAttribute("rel")).toBe("noopener noreferrer");
});

test("available titles expose separate focusable Plex web and app links", async () => {
	stubTasteFetch({
		"/api/v1/title/": {
			...DETAIL,
			availability: {
				status: "available",
				known: true,
				playback: {
					regular: {
						web_url: "https://app.plex.tv/desktop/#!/details",
						app_url: "plex://preplay/?metadataKey=x",
						android_intent_url: "intent://preplay/#Intent;end",
					},
					four_k: null,
				},
			},
		},
		"/api/v1/signals": { recorded: true },
	});
	vi.stubGlobal("navigator", { userAgent: "Mozilla/5.0 (X11; Linux x86_64)" });
	renderModal();

	const web = await screen.findByRole("link", {
		name: "Play in Plex Web (opens in a new tab)",
	});
	const app = screen.getByRole("link", { name: "Play in Plex App" });
	expect(web.getAttribute("href")).toBe(
		"https://app.plex.tv/desktop/#!/details",
	);
	expect(app.getAttribute("href")).toBe("plex://preplay/?metadataKey=x");
	expect(web.getAttribute("target")).toBe("_blank");
	expect(web.getAttribute("rel")).toBe("noopener noreferrer");
	expect(app.getAttribute("rel")).toBe("noreferrer");
	const guidance = screen.getByText(
		"Experimental. Plex Web may need a second try after sign-in or switching users. Plex App may open Home instead.",
	);
	expect(guidance.getAttribute("id")).toBe("plex-playback-experimental");
	expect(web.getAttribute("aria-describedby")).toBe(
		"plex-playback-experimental",
	);
	expect(app.getAttribute("aria-describedby")).toBe(
		"plex-playback-experimental",
	);
	web.focus();
	expect(document.activeElement).toBe(web);
	app.focus();
	expect(document.activeElement).toBe(app);
});

test("Android keeps Plex Web and uses the server-provided app intent", async () => {
	stubTasteFetch({
		"/api/v1/title/": {
			...DETAIL,
			availability: {
				status: "available",
				known: true,
				playback: {
					regular: {
						web_url: "https://app.plex.tv/desktop/#!/details",
						app_url: "plex://preplay/?metadataKey=x",
						android_intent_url:
							"intent://preplay/#Intent;package=com.plexapp.android;S.browser_fallback_url=https%3A%2F%2Fapp.plex.tv;end",
					},
					four_k: null,
				},
			},
		},
		"/api/v1/signals": { recorded: true },
	});
	vi.stubGlobal("navigator", { userAgent: "Mozilla/5.0 (Linux; Android 16)" });
	renderModal();

	expect(
		(
			await screen.findByRole("link", {
				name: "Play in Plex Web (opens in a new tab)",
			})
		).getAttribute("href"),
	).toBe("https://app.plex.tv/desktop/#!/details");
	expect(
		screen.getByRole("link", { name: "Play in Plex App" }).getAttribute("href"),
	).toContain("package=com.plexapp.android");
});

test("partially available regular playback is preferred over playable 4K", async () => {
	stubTasteFetch({
		"/api/v1/title/": {
			...DETAIL,
			availability: {
				status: "partial",
				known: true,
				playback: {
					regular: {
						web_url: "https://app.plex.tv/desktop#!/partial",
						app_url: "plex://preplay/?metadataKey=partial",
						android_intent_url: null,
					},
					four_k: {
						web_url: "https://app.plex.tv/desktop#!/4k",
						app_url: "plex://preplay/?metadataKey=4k",
						android_intent_url: null,
					},
				},
			},
		},
		"/api/v1/signals": { recorded: true },
	});
	vi.stubGlobal("navigator", { userAgent: "Mozilla/5.0 (X11; Linux x86_64)" });
	renderModal();

	const web = await screen.findByRole("link", {
		name: "Play in Plex Web (opens in a new tab)",
	});
	const app = screen.getByRole("link", { name: "Play in Plex App" });
	expect(web.getAttribute("href")).toBe(
		"https://app.plex.tv/desktop#!/partial",
	);
	expect(app.getAttribute("href")).toBe("plex://preplay/?metadataKey=partial");
});

test("playback links fall back to 4K and omit an unavailable app target", async () => {
	stubTasteFetch({
		"/api/v1/title/": {
			...DETAIL,
			availability: {
				status: "available",
				known: true,
				playback: {
					regular: null,
					four_k: {
						web_url: "https://app.plex.tv/desktop/#!/4k",
						app_url: null,
						android_intent_url: null,
					},
				},
			},
		},
		"/api/v1/signals": { recorded: true },
	});
	renderModal();

	expect(
		(
			await screen.findByRole("link", {
				name: "Play in Plex Web (opens in a new tab)",
			})
		).getAttribute("href"),
	).toBe("https://app.plex.tv/desktop/#!/4k");
	expect(screen.queryByRole("link", { name: "Play in Plex App" })).toBeNull();

	cleanup();
	stubTasteFetch({
		"/api/v1/title/": {
			...DETAIL,
			availability: { status: "available", known: true, playback: null },
		},
		"/api/v1/signals": { recorded: true },
	});
	renderModal();
	await screen.findByRole("heading", { name: "Deep Movie" });
	expect(
		screen.queryByRole("link", {
			name: "Play in Plex Web (opens in a new tab)",
		}),
	).toBeNull();
	expect(screen.queryByRole("link", { name: "Play in Plex App" })).toBeNull();
});

test("traps focus, marks the browse shell inert, and cleans up on Escape", async () => {
	const background = document.createElement("div");
	background.id = "shell-background";
	document.body.append(background);
	vi.stubGlobal(
		"fetch",
		vi.fn(
			async () =>
				({ ok: true, status: 200, json: async () => DETAIL }) as Response,
		),
	);
	renderModal();
	const close = screen.getByRole("button", { name: "Close" });
	expect(document.activeElement).toBe(close);
	expect(background.inert).toBe(true);
	await screen.findByRole("heading", { name: "Deep Movie" });
	const dialog = screen.getByRole("dialog");
	const focusable = Array.from(
		dialog.querySelectorAll<HTMLElement>(
			"a[href],button:not([disabled]),iframe",
		),
	);
	const last = focusable.at(-1) as HTMLElement;
	last.focus();
	fireEvent.keyDown(document, { key: "Tab" });
	expect(document.activeElement).toBe(close);
	close.focus();
	fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
	expect(document.activeElement).toBe(last);
	dialog.focus();
	fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
	expect(document.activeElement).toBe(last);
	dialog.focus();
	fireEvent.keyDown(document, { key: "Tab" });
	expect(document.activeElement).toBe(close);
	fireEvent.keyDown(document, { key: "Escape" });
	expect(screen.queryByRole("dialog")).toBeNull();
	expect(background.inert).toBe(false);
	background.remove();
});

test("locks body scrolling and restores the previous overflow on close", async () => {
	document.body.style.overflow = "scroll";
	vi.stubGlobal(
		"fetch",
		vi.fn(
			async () =>
				({ ok: true, status: 200, json: async () => DETAIL }) as Response,
		),
	);
	renderModal();

	expect(document.body.style.overflow).toBe("hidden");
	fireEvent.click(screen.getByRole("button", { name: "Close" }));

	expect(document.body.style.overflow).toBe("scroll");
});

test("related titles replace the modal route and close to the browse view", async () => {
	stubTasteFetch({
		"/api/v1/title/movie/42": {
			...DETAIL,
			recommendations: [summary(43, "Other Movie")],
		},
		"/api/v1/title/movie/43": {
			...DETAIL,
			id: 43,
			title: "Other Movie",
			external_url: "https://www.themoviedb.org/movie/43",
			recommendations: [summary(44, "Third Movie")],
		},
		"/api/v1/title/movie/44": {
			...DETAIL,
			id: 44,
			title: "Third Movie",
			external_url: "https://www.themoviedb.org/movie/44",
		},
		"/api/v1/signals": { recorded: true },
		"/api/v1/availability": {},
	});
	renderModal(["/"]);

	fireEvent.click(screen.getByRole("link", { name: /Deep Movie/ }));
	const related = await screen.findByRole("link", { name: /Other Movie/ });
	related.focus();
	fireEvent.click(related);
	await screen.findByRole("heading", { name: "Other Movie" });
	expect(document.activeElement).toBe(screen.getByRole("dialog"));
	fireEvent.click(await screen.findByRole("link", { name: /Third Movie/ }));
	expect(
		await screen.findByRole("heading", { name: "Third Movie" }),
	).toBeTruthy();

	fireEvent.click(screen.getByRole("button", { name: "Close" }));
	expect(await screen.findByRole("link", { name: /Deep Movie/ })).toBeTruthy();
	expect(screen.queryByRole("dialog")).toBeNull();
});

test("a related title from a direct detail still closes to Home", async () => {
	stubTasteFetch({
		"/api/v1/title/movie/42": {
			...DETAIL,
			recommendations: [summary(43, "Other Movie")],
		},
		"/api/v1/title/movie/43": {
			...DETAIL,
			id: 43,
			title: "Other Movie",
			external_url: "https://www.themoviedb.org/movie/43",
		},
		"/api/v1/signals": { recorded: true },
		"/api/v1/availability": {},
	});
	renderModal();

	fireEvent.click(await screen.findByRole("link", { name: /Other Movie/ }));
	expect(
		await screen.findByRole("heading", { name: "Other Movie" }),
	).toBeTruthy();
	fireEvent.click(screen.getByRole("button", { name: "Close" }));

	expect(await screen.findByRole("link", { name: /Deep Movie/ })).toBeTruthy();
	expect(screen.queryByRole("dialog")).toBeNull();
});

// ── Taste affordances (M4) ───────────────────────────────────────────────────

type RecordedCall = { url: string; body: unknown };

/** Route by URL substring, record every call; a "reject" route throws. */
function stubTasteFetch(routes: Record<string, unknown | "reject">) {
	const calls: RecordedCall[] = [];
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = String(input);
			const body =
				typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
			calls.push({ url, body });
			for (const [path, result] of Object.entries(routes)) {
				if (url.includes(path)) {
					if (result === "reject") {
						throw new TypeError("network down");
					}
					return {
						ok: true,
						status: 200,
						json: async () => result,
					} as Response;
				}
			}
			return { ok: true, status: 200, json: async () => DETAIL } as Response;
		}),
	);
	return calls;
}

function signalCalls(calls: RecordedCall[]): RecordedCall[] {
	return calls.filter((call) => call.url.includes("/api/v1/signals"));
}

test("opening a detail fires a detail_open signal without blocking render", async () => {
	const calls = stubTasteFetch({ "/api/v1/signals": { recorded: true } });
	renderModal();

	expect(
		await screen.findByRole("heading", { name: "Deep Movie" }),
	).toBeTruthy();
	await waitFor(() => expect(signalCalls(calls).length).toBe(1));
	expect(signalCalls(calls)[0].body).toEqual({
		media_type: "movie",
		tmdb_id: 42,
		kind: "detail_open",
		retract: false,
	});
});

test("a failed detail_open leaves the view untouched", async () => {
	stubTasteFetch({ "/api/v1/signals": "reject" });
	renderModal();

	expect(
		await screen.findByRole("heading", { name: "Deep Movie" }),
	).toBeTruthy();
	expect(screen.queryByText("Could not load this title.")).toBeNull();
});

test("watchlist toggles optimistically and posts add then retract", async () => {
	const calls = stubTasteFetch({ "/api/v1/signals": { recorded: true } });
	renderModal();
	const button = await screen.findByRole("button", { name: "＋ My List" });

	fireEvent.click(button);
	expect(screen.getByRole("button", { name: "✓ In My List" })).toBeTruthy();
	await waitFor(() =>
		expect(
			signalCalls(calls).some(
				(call) =>
					(call.body as { kind?: string; retract?: boolean }).kind ===
						"watchlist" &&
					(call.body as { retract?: boolean }).retract === false,
			),
		).toBe(true),
	);

	fireEvent.click(screen.getByRole("button", { name: "✓ In My List" }));
	expect(
		await screen.findByRole("button", { name: "＋ My List" }),
	).toBeTruthy();
	await waitFor(() =>
		expect(
			signalCalls(calls).some(
				(call) =>
					(call.body as { kind?: string; retract?: boolean }).kind ===
						"watchlist" &&
					(call.body as { retract?: boolean }).retract === true,
			),
		).toBe(true),
	);
});

test("reopened cached detail adopts the refreshed watchlist state", async () => {
	let watchlisted = false;
	let titleReads = 0;
	let releaseRefresh = () => {};
	const refreshBlocked = new Promise<void>((resolve) => {
		releaseRefresh = resolve;
	});
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = String(input);
			if (url.includes("/api/v1/title/movie/42")) {
				titleReads += 1;
				if (titleReads > 1) {
					await refreshBlocked;
				}
				return {
					ok: true,
					status: 200,
					json: async () => ({
						...DETAIL,
						taste: { watchlisted, hidden: false },
					}),
				} as Response;
			}
			if (url.includes("/api/v1/signals")) {
				const body =
					typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
				if (body?.kind === "watchlist") {
					watchlisted = !body.retract;
				}
				return {
					ok: true,
					status: 200,
					json: async () => ({ recorded: true }),
				} as Response;
			}
			return {
				ok: true,
				status: 200,
				json: async () => ({}),
			} as Response;
		}),
	);
	renderModal(["/"]);

	fireEvent.click(screen.getByRole("link", { name: /Deep Movie/ }));
	fireEvent.click(await screen.findByRole("button", { name: "＋ My List" }));
	await waitFor(() => expect(watchlisted).toBe(true));
	fireEvent.click(screen.getByRole("button", { name: "Close" }));
	fireEvent.click(await screen.findByRole("link", { name: /Deep Movie/ }));

	expect(
		await screen.findByRole("button", { name: "＋ My List" }),
	).toBeTruthy();
	releaseRefresh();
	expect(
		await screen.findByRole("button", { name: "✓ In My List" }),
	).toBeTruthy();
});

test("not-interested offers an undo and a failed post reverts the flip", async () => {
	stubTasteFetch({ "/api/v1/signals": "reject" });
	renderModal();
	const button = await screen.findByRole("button", { name: "Not interested" });

	fireEvent.click(button);

	// Optimistic flip to the undo affordance, then revert once the post fails.
	expect(screen.getByRole("button", { name: "Hidden — undo" })).toBeTruthy();
	expect(
		await screen.findByRole("button", { name: "Not interested" }),
	).toBeTruthy();
});

test("initial toggle state comes from the detail's taste flags", async () => {
	stubTasteFetch({
		"/api/v1/title/": {
			...DETAIL,
			taste: { watchlisted: true, hidden: false },
		},
		"/api/v1/signals": { recorded: true },
	});
	renderModal();

	expect(
		await screen.findByRole("button", { name: "✓ In My List" }),
	).toBeTruthy();
	expect(screen.getByRole("button", { name: "Not interested" })).toBeTruthy();
});

test("toggle state resets when navigating between cached titles in-modal", async () => {
	// The stale-state hazard needs a *cached* target: uncached navigations
	// unmount DetailBody while loading, which resets state by accident.
	// Visit 42 → 43 → back to 42 (now cached, renders synchronously).
	stubTasteFetch({
		"/api/v1/title/movie/42": {
			...DETAIL,
			taste: { watchlisted: true, hidden: false },
			recommendations: [summary(43, "Other Movie")],
		},
		"/api/v1/title/movie/43": {
			...DETAIL,
			id: 43,
			title: "Other Movie",
			taste: { watchlisted: false, hidden: false },
			recommendations: [summary(42, "Deep Movie")],
		},
		"/api/v1/signals": { recorded: true },
		"/api/v1/availability": {},
	});
	renderModal();
	expect(
		await screen.findByRole("button", { name: "✓ In My List" }),
	).toBeTruthy();

	fireEvent.click(screen.getByRole("link", { name: /Other Movie/ }));
	expect(
		await screen.findByRole("button", { name: "＋ My List" }),
	).toBeTruthy();

	fireEvent.click(screen.getByRole("link", { name: /Deep Movie/ }));

	// Back on 42 (cached): its own watchlisted=true flags must win, not the
	// carried-over state from 43.
	expect(
		await screen.findByRole("button", { name: "✓ In My List" }),
	).toBeTruthy();
});

test("explain loads lazily and lists reasons as text", async () => {
	const calls = stubTasteFetch({
		"/api/v1/signals": { recorded: true },
		"/api/v1/recommendations/explain": {
			personalized: true,
			reasons: ["Science Fiction", "time travel"],
		},
	});
	renderModal();
	const toggle = await screen.findByRole("button", {
		name: "Why am I seeing this?",
	});
	expect(
		calls.some((call) => call.url.includes("/recommendations/explain")),
	).toBe(false); // nothing fetched before the user asks

	fireEvent.click(toggle);

	expect(
		await screen.findByText("Because you like: Science Fiction, time travel"),
	).toBeTruthy();
});

test("explain shows the honest empty state when not personalized", async () => {
	stubTasteFetch({
		"/api/v1/signals": { recorded: true },
		"/api/v1/recommendations/explain": { personalized: false, reasons: [] },
	});
	renderModal();

	fireEvent.click(
		await screen.findByRole("button", { name: "Why am I seeing this?" }),
	);

	expect(await screen.findByText(/Not personalized yet/)).toBeTruthy();
});
