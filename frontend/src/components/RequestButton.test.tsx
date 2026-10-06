import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	act,
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { Availability, RequestOptions, SeasonSummary } from "../lib/api";
import { RequestButton } from "./RequestButton";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

function av(
	status: Availability["status"],
	fourK: Availability["status"] = "not_requested",
): Availability {
	return {
		status,
		known: status !== "unknown",
		regular_status: status,
		four_k_status: status === "unknown" ? "unknown" : fourK,
	};
}
const SERVER = {
	server_id: 0,
	server_name: "Radarr",
	is_default: true,
	is_4k: false,
	default_profile_id: 7,
	default_root_folder: "/movies",
	quality_profiles: [
		{ id: 7, name: "HD" },
		{ id: 4, name: "1080p" },
	],
	root_folders: [
		{ id: 1, path: "/movies" },
		{ id: 2, path: "/new" },
	],
};
const FOUR_K = {
	...SERVER,
	server_id: 1,
	server_name: "Radarr 4K",
	is_4k: true,
	default_root_folder: "/4k",
	root_folders: [{ id: 3, path: "/4k" }],
};
const OPTIONS: RequestOptions = {
	available: true,
	can_request_standard: true,
	can_request_4k: false,
	can_request_4k_default: false,
	can_override: true,
	can_request_specials: true,
	can_request_partial: true,
	destinations: [SERVER],
};
const BOTH: RequestOptions = {
	...OPTIONS,
	can_request_4k: true,
	can_request_4k_default: true,
	destinations: [FOUR_K, SERVER],
};
function response(body: unknown, status = 200): Response {
	return { ok: status < 400, status, json: async () => body } as Response;
}
function fixture(
	options: RequestOptions = OPTIONS,
	outcome: unknown = {
		status: "ok",
		availability: av("pending"),
		seerr_url: null,
	},
	mutationStatus = 200,
) {
	const bodies: unknown[] = [];
	const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
		const url = String(input);
		if (url.includes("/config")) return response({ seerr_configured: true });
		if (url.includes("/destinations")) return response(options);
		if (url.endsWith("/request")) {
			bodies.push(JSON.parse(String(init?.body)));
			return response(outcome, mutationStatus);
		}
		return response({}, 404);
	});
	vi.stubGlobal("fetch", fetch);
	return { fetch, bodies };
}
function renderButton(
	availability: Availability = av("not_requested"),
	client = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	}),
	id = 42,
) {
	render(
		<QueryClientProvider client={client}>
			<RequestButton type="movie" id={id} availability={availability} />
		</QueryClientProvider>,
	);
	return client;
}

test("ordinary requesting omits overrides and the standard flag", async () => {
	const { bodies } = fixture();
	renderButton();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	await screen.findByText("Requested ✓");
	expect(bodies).toEqual([{ media_type: "movie", tmdb_id: 42 }]);
});

test("advanced defaults remain bare even after opening confirmation", async () => {
	const { bodies } = fixture();
	renderButton();
	fireEvent.click(
		await screen.findByRole("button", { name: "Choose destination" }),
	);
	expect(
		screen.getByRole("combobox", { name: "Server" }).getAttribute("value"),
	).toBeNull();
	expect(
		(screen.getByRole("combobox", { name: "Server" }) as HTMLSelectElement)
			.value,
	).toBe("default");
	fireEvent.click(screen.getByRole("button", { name: "Confirm request" }));
	await screen.findByText("Requested ✓");
	expect(bodies).toEqual([{ media_type: "movie", tmdb_id: 42 }]);
});

test("explicit advanced profile/folder selection is forwarded", async () => {
	const { bodies } = fixture();
	renderButton();
	fireEvent.click(
		await screen.findByRole("button", { name: "Choose destination" }),
	);
	fireEvent.change(screen.getByRole("combobox", { name: "Server" }), {
		target: { value: "0" },
	});
	fireEvent.change(screen.getByRole("combobox", { name: "Quality Profile" }), {
		target: { value: "4" },
	});
	fireEvent.change(screen.getByRole("combobox", { name: "Root Folder" }), {
		target: { value: "/new" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Confirm request" }));
	await screen.findByText("Requested ✓");
	expect(bodies).toEqual([
		{
			media_type: "movie",
			tmdb_id: 42,
			server_id: 0,
			profile_id: 4,
			root_folder: "/new",
		},
	]);
});

test("4K first in discovery does not change the standard default", async () => {
	const { bodies } = fixture(BOTH);
	renderButton();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	await screen.findByText("Requested ✓");
	expect(bodies[0]).toEqual({ media_type: "movie", tmdb_id: 42 });
});

test("4K quality sends explicit flag without overriding Seerr defaults", async () => {
	const { bodies } = fixture(BOTH);
	renderButton();
	fireEvent.change(await screen.findByRole("combobox", { name: "Quality" }), {
		target: { value: "4k" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Request 4K" }));
	await screen.findByText("Requested ✓");
	expect(bodies).toEqual([{ media_type: "movie", tmdb_id: 42, is_4k: true }]);
});

test("advanced 4K picker excludes standard servers and preserves flag", async () => {
	const { bodies } = fixture(BOTH);
	renderButton();
	fireEvent.change(await screen.findByRole("combobox", { name: "Quality" }), {
		target: { value: "4k" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Choose destination" }));
	expect(screen.queryByRole("option", { name: "Radarr" })).toBeNull();
	fireEvent.change(screen.getByRole("combobox", { name: "Server" }), {
		target: { value: "1" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Confirm request" }));
	await screen.findByText("Requested ✓");
	expect(bodies).toEqual([
		{
			media_type: "movie",
			tmdb_id: 42,
			is_4k: true,
			server_id: 1,
			profile_id: 7,
			root_folder: "/4k",
		},
	]);
});

test.each([
	"available",
	"pending",
	"processing",
	"partial",
] as const)("missing 4K remains requestable when standard is %s", async (status) => {
	const { bodies } = fixture({
		...BOTH,
		can_override: false,
		destinations: [],
	});
	renderButton(av(status));
	fireEvent.click(await screen.findByRole("button", { name: "Request 4K" }));
	await screen.findByText("Requested ✓");
	expect(bodies[0]).toEqual({ media_type: "movie", tmdb_id: 42, is_4k: true });
});

test("cancel discards explicit selection and returns to defaults", async () => {
	const { bodies } = fixture();
	renderButton();
	fireEvent.click(
		await screen.findByRole("button", { name: "Choose destination" }),
	);
	fireEvent.change(screen.getByRole("combobox", { name: "Server" }), {
		target: { value: "0" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
	expect(screen.queryByRole("combobox", { name: "Server" })).toBeNull();
	fireEvent.click(screen.getByRole("button", { name: "Request" }));
	await screen.findByText("Requested ✓");
	expect(bodies[0]).toEqual({ media_type: "movie", tmdb_id: 42 });
});

test.each([
	"server",
	"profile",
	"folder",
])("refetch removing chosen %s blocks confirmation", async (kind) => {
	const { bodies } = fixture();
	const client = renderButton();
	fireEvent.click(
		await screen.findByRole("button", { name: "Choose destination" }),
	);
	fireEvent.change(screen.getByRole("combobox", { name: "Server" }), {
		target: { value: "0" },
	});
	const servers =
		kind === "server"
			? []
			: [
					{
						...SERVER,
						quality_profiles:
							kind === "profile"
								? [{ id: 4, name: "1080p" }]
								: SERVER.quality_profiles,
						root_folders:
							kind === "folder"
								? [{ id: 2, path: "/new" }]
								: SERVER.root_folders,
					},
				];
	act(() =>
		client.setQueryData(["destinations", "movie"], {
			...OPTIONS,
			destinations: servers,
		}),
	);
	expect((await screen.findByRole("alert")).textContent).toContain(
		"no longer available",
	);
	expect(
		(
			screen.getByRole("button", {
				name: "Confirm request",
			}) as HTMLButtonElement
		).disabled,
	).toBe(true);
	fireEvent.click(screen.getByRole("button", { name: "Confirm request" }));
	expect(bodies).toEqual([]);
	fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
	expect(
		(
			screen.getByRole("button", {
				name: "Request",
			}) as HTMLButtonElement
		).disabled,
	).toBe(false);
});

test("pending discovery cannot submit a bare request", async () => {
	let resolve: (value: Response) => void = () => {};
	const pending = new Promise<Response>((done) => {
		resolve = done;
	});
	const bodies: unknown[] = [];
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
			if (String(input).includes("/config"))
				return response({ seerr_configured: true });
			if (String(input).includes("/destinations")) return pending;
			bodies.push(init?.body);
			return response({ status: "ok" });
		}),
	);
	renderButton();
	const loading = await screen.findByRole("button", {
		name: "Loading request options…",
	});
	fireEvent.click(loading);
	expect(bodies).toEqual([]);
	await act(async () => {
		resolve(response(BOTH));
	});
	expect(await screen.findByRole("combobox", { name: "Quality" })).toBeTruthy();
	expect(bodies).toEqual([]);
});

test("non-2xx mutation displays error and allows retry", async () => {
	fixture(OPTIONS, { detail: "Unknown request destination" }, 422);
	renderButton();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	expect((await screen.findByRole("alert")).textContent).toContain(
		"Couldn’t send",
	);
	expect(
		(
			screen.getByRole("button", {
				name: "Request",
			}) as HTMLButtonElement
		).disabled,
	).toBe(false);
});

test("failed discovery allows standard defaults without authorizing 4K", async () => {
	const { bodies } = fixture({
		...OPTIONS,
		available: false,
		can_request_4k: false,
		can_request_4k_default: false,
		destinations: [],
	});
	renderButton();
	expect(screen.queryByRole("button", { name: "Request 4K" })).toBeNull();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	await screen.findByText("Requested ✓");
	expect(bodies[0]).toEqual({ media_type: "movie", tmdb_id: 42 });
});

test("server-built fallback and expired session are visible", async () => {
	fixture(OPTIONS, {
		status: "failed",
		seerr_url: "https://requests.example/movie/42",
	});
	renderButton();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	expect(
		(
			await screen.findByRole("link", { name: /Request in Seerr/ })
		).getAttribute("href"),
	).toBe("https://requests.example/movie/42");
});

test("expired session prompts sign-in", async () => {
	fixture(OPTIONS, { status: "re_auth_required" });
	renderButton();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	expect((await screen.findByRole("alert")).textContent).toContain(
		"sign in again",
	);
});

test("discovery is shared across titles of one media type", async () => {
	const { fetch } = fixture();
	const client = renderButton();
	renderButton(av("not_requested"), client, 43);
	await screen.findAllByRole("button", { name: "Request" });
	expect(
		fetch.mock.calls.filter(([url]) => String(url).includes("/destinations")),
	).toHaveLength(1);
});

test.each([
	av("unknown"),
	av("available", "available"),
])("no discovery when no known variant is missing", async (availability) => {
	const { fetch } = fixture();
	renderButton(availability);
	await waitFor(() => expect(fetch).toHaveBeenCalled());
	expect(
		fetch.mock.calls.filter(([url]) => String(url).includes("/destinations")),
	).toHaveLength(0);
	expect(screen.queryByRole("button")).toBeNull();
});

test("no affordance or discovery when Seerr is unconfigured", async () => {
	const fetch = vi.fn(async () => response({ seerr_configured: false }));
	vi.stubGlobal("fetch", fetch);
	renderButton();
	await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
	expect(screen.queryByRole("button")).toBeNull();
});

test("4K success preserves standard availability and playback in the detail cache", async () => {
	fixture({ ...BOTH, can_override: false, destinations: [] });
	const previous: Availability = {
		...av("available"),
		playback: {
			regular: { web_url: "https://app.plex.tv/desktop#!/fixture" },
			four_k: null,
		},
	};
	const client = renderButton(previous);
	client.setQueryData(["title", "movie", 42], { availability: previous });
	fireEvent.click(await screen.findByRole("button", { name: "Request 4K" }));
	await screen.findByText("Requested ✓");
	expect(
		client.getQueryData<{ availability: Availability }>(["title", "movie", 42])
			?.availability,
	).toMatchObject({
		status: "available",
		regular_status: "available",
		four_k_status: "pending",
		playback: previous.playback,
	});
});

test("4K without a default requires an explicit advanced destination", async () => {
	const { bodies } = fixture({
		...BOTH,
		can_request_4k_default: false,
		destinations: [{ ...FOUR_K, is_default: false }],
	});
	renderButton(av("available"));
	const request = await screen.findByRole("button", { name: "Request 4K" });
	expect((request as HTMLButtonElement).disabled).toBe(true);
	fireEvent.click(request);
	expect(bodies).toEqual([]);
	expect(screen.getByRole("alert").textContent).toContain("No default 4K");
	fireEvent.click(screen.getByRole("button", { name: "Choose destination" }));
	fireEvent.change(screen.getByRole("combobox", { name: "Server" }), {
		target: { value: "1" },
	});
	const confirm = screen.getByRole("button", { name: "Confirm request" });
	expect((confirm as HTMLButtonElement).disabled).toBe(false);
	fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
	expect(
		(screen.getByRole("button", { name: "Request 4K" }) as HTMLButtonElement)
			.disabled,
	).toBe(true);
	fireEvent.click(screen.getByRole("button", { name: "Choose destination" }));
	fireEvent.change(screen.getByRole("combobox", { name: "Server" }), {
		target: { value: "1" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Confirm request" }));
	await waitFor(() =>
		expect(bodies).toEqual([
			{
				media_type: "movie",
				tmdb_id: 42,
				is_4k: true,
				server_id: 1,
				profile_id: 7,
				root_folder: "/4k",
			},
		]),
	);
});

test("losing the 4K default during refetch blocks bare confirmation", async () => {
	const { bodies } = fixture(BOTH);
	const client = renderButton(av("available"));
	const button = await screen.findByRole("button", { name: "Request 4K" });
	expect((button as HTMLButtonElement).disabled).toBe(false);
	act(() =>
		client.setQueryData(["destinations", "movie"], {
			...BOTH,
			can_request_4k_default: false,
		}),
	);
	await screen.findByRole("alert");
	expect((button as HTMLButtonElement).disabled).toBe(true);
	fireEvent.click(button);
	expect(bodies).toEqual([]);
});

const SEASONS: SeasonSummary[] = [0, 1, 2, 3].map((n) => ({
	season_number: n,
	name: n === 0 ? "Specials" : `Season ${n}`,
	episode_count: 10,
	air_date: null,
}));
function toggle(name: RegExp | string): HTMLElement {
	return screen.getByRole("switch", { name });
}
function renderTv(seasons = SEASONS) {
	const client = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={client}>
			<RequestButton
				type="tv"
				id={7}
				availability={av("not_requested")}
				seasons={seasons}
			/>
		</QueryClientProvider>,
	);
	return client;
}

test("request opens a season dialog with regular seasons on and Specials off", async () => {
	const { bodies } = fixture();
	renderTv();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	screen.getByRole("dialog", { name: "Choose seasons" });
	expect(toggle(/Specials/).getAttribute("aria-checked")).toBe("false");
	for (const name of [/Season 1/, /Season 2/, /Season 3/])
		expect(toggle(name).getAttribute("aria-checked")).toBe("true");
	expect(bodies).toEqual([]);
});

test("OK with the default seasons keeps the whole-series request", async () => {
	const { bodies } = fixture();
	renderTv();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	fireEvent.click(screen.getByRole("button", { name: "OK" }));
	await screen.findByText("Requested ✓");
	expect(bodies).toEqual([{ media_type: "tv", tmdb_id: 7 }]);
});

test("OK sends only the chosen seasons, Specials included", async () => {
	const { bodies } = fixture();
	renderTv();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	fireEvent.click(toggle(/Season 1/));
	fireEvent.click(toggle(/Specials/));
	fireEvent.click(screen.getByRole("button", { name: "OK" }));
	await screen.findByText("Requested ✓");
	expect(bodies).toEqual([
		{ media_type: "tv", tmdb_id: 7, seasons: [0, 2, 3] },
	]);
});

test("no season chosen blocks OK", async () => {
	const { bodies } = fixture();
	renderTv();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	fireEvent.click(toggle("All seasons")); // everything on, Specials included
	fireEvent.click(toggle("All seasons")); // everything off
	screen.getByText("Choose at least one season.");
	expect(
		(screen.getByRole("button", { name: "OK" }) as HTMLButtonElement).disabled,
	).toBe(true);
	expect(bodies).toEqual([]);
});

test("cancel closes the dialog without requesting and resets choices", async () => {
	const { bodies } = fixture();
	renderTv();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	fireEvent.click(toggle(/Season 2/));
	fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
	expect(screen.queryByRole("dialog")).toBeNull();
	fireEvent.click(screen.getByRole("button", { name: "Request" }));
	expect(toggle(/Season 2/).getAttribute("aria-checked")).toBe("true");
	expect(bodies).toEqual([]);
});

test("escape cancels the season request", async () => {
	fixture();
	renderTv();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	fireEvent.keyDown(document, { key: "Escape" });
	expect(screen.queryByRole("dialog")).toBeNull();
});

test("a single-season show requests directly without a dialog", async () => {
	const { bodies } = fixture();
	renderTv(SEASONS.slice(1, 2));
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	await screen.findByText("Requested ✓");
	expect(bodies).toEqual([{ media_type: "tv", tmdb_id: 7 }]);
});

test.each([
	{ ...OPTIONS, can_request_specials: false },
	{ ...OPTIONS, available: false, can_request_specials: false },
])("disabled or unknown Specials are not selectable", async (options) => {
	const { bodies } = fixture(options);
	renderTv();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	expect(screen.queryByRole("switch", { name: /Specials/ })).toBeNull();
	fireEvent.click(toggle(/Season 1/));
	fireEvent.click(screen.getByRole("button", { name: "OK" }));
	await screen.findByText("Requested ✓");
	expect(bodies).toEqual([{ media_type: "tv", tmdb_id: 7, seasons: [2, 3] }]);
});

const EMPTY_AND_FUTURE = [
	...SEASONS,
	{
		season_number: 4,
		name: "Empty season",
		episode_count: 0,
		air_date: "2099-01-01",
	},
	{
		season_number: 5,
		name: "Future season",
		episode_count: 8,
		air_date: "2099-01-01",
	},
];

test("default equivalence excludes empty seasons but keeps future seasons with episodes", async () => {
	const { bodies } = fixture();
	renderTv(EMPTY_AND_FUTURE);
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	expect(screen.queryByRole("switch", { name: /Empty season/ })).toBeNull();
	expect(toggle(/Future season/).getAttribute("aria-checked")).toBe("true");
	fireEvent.click(screen.getByRole("button", { name: "OK" }));
	await screen.findByText("Requested ✓");
	expect(bodies).toEqual([{ media_type: "tv", tmdb_id: 7 }]);
});

test("All seasons and explicit subsets exclude zero-episode seasons", async () => {
	const { bodies } = fixture();
	renderTv(EMPTY_AND_FUTURE);
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	fireEvent.click(toggle("All seasons"));
	fireEvent.click(toggle(/Season 1/));
	fireEvent.click(screen.getByRole("button", { name: "OK" }));
	await screen.findByText("Requested ✓");
	expect(bodies).toEqual([
		{ media_type: "tv", tmdb_id: 7, seasons: [0, 2, 3, 5] },
	]);
});

test("one eligible regular season requests directly when Specials are disabled", async () => {
	const { bodies } = fixture({ ...OPTIONS, can_request_specials: false });
	renderTv([SEASONS[0], SEASONS[1], EMPTY_AND_FUTURE[4]]);
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	await screen.findByText("Requested ✓");
	expect(screen.queryByRole("dialog")).toBeNull();
	expect(bodies).toEqual([{ media_type: "tv", tmdb_id: 7 }]);
});

test("losing Specials support while open blocks an empty visible choice", async () => {
	const { bodies } = fixture();
	const client = renderTv();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	fireEvent.click(toggle("All seasons"));
	for (const name of [/Season 1/, /Season 2/, /Season 3/])
		fireEvent.click(toggle(name));
	act(() =>
		client.setQueryData(["destinations", "tv"], {
			...OPTIONS,
			can_request_specials: false,
		}),
	);
	await screen.findByText("Choose at least one season.");
	expect(screen.queryByRole("switch", { name: /Specials/ })).toBeNull();
	expect(
		(screen.getByRole("button", { name: "OK" }) as HTMLButtonElement).disabled,
	).toBe(true);
	expect(bodies).toEqual([]);
});

test.each([
	{
		name: "4K permission",
		options: { ...BOTH, can_request_4k: false },
		advanced: false,
	},
	{
		name: "4K default",
		options: { ...BOTH, can_request_4k_default: false },
		advanced: false,
	},
	{
		name: "discovery availability",
		options: { ...BOTH, available: false },
		advanced: false,
	},
	{
		name: "advanced permission",
		options: { ...BOTH, can_override: false },
		advanced: true,
	},
	{
		name: "server",
		options: { ...BOTH, destinations: [SERVER] },
		advanced: true,
	},
	{
		name: "profile",
		options: {
			...BOTH,
			destinations: [{ ...FOUR_K, quality_profiles: [] }, SERVER],
		},
		advanced: true,
	},
	{
		name: "root folder",
		options: {
			...BOTH,
			destinations: [{ ...FOUR_K, root_folders: [] }, SERVER],
		},
		advanced: true,
	},
])("season confirmation respects refreshed $name", async ({
	options,
	advanced,
}) => {
	const { bodies } = fixture(BOTH);
	const client = renderTv();
	await screen.findByRole("button", { name: "Request" });
	fireEvent.change(screen.getByRole("combobox", { name: "Quality" }), {
		target: { value: "4k" },
	});
	if (advanced) {
		fireEvent.click(screen.getByRole("button", { name: "Choose destination" }));
		fireEvent.change(screen.getByRole("combobox", { name: "Server" }), {
			target: { value: "1" },
		});
	}
	const request = screen.getByRole("button", {
		name: advanced ? "Confirm request" : "Request 4K",
	});
	fireEvent.click(request);
	screen.getByRole("dialog", { name: "Choose seasons" });
	act(() => client.setQueryData(["destinations", "tv"], options));
	await waitFor(() =>
		expect((request as HTMLButtonElement).disabled).toBe(true),
	);
	await act(async () => {
		fireEvent.click(screen.getByRole("button", { name: "OK" }));
	});
	expect(bodies).toEqual([]);
	expect(screen.queryByText("Requested ✓")).toBeNull();
});

test.each([
	[SEASONS[0]],
	[SEASONS[0], { ...SEASONS[1], episode_count: 0 }],
])("Specials as the sole eligible season requests season zero directly", async (...seasons) => {
	const { bodies } = fixture();
	renderTv(seasons);
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	await screen.findByText("Requested ✓");
	expect(screen.queryByRole("dialog")).toBeNull();
	expect(bodies).toEqual([{ media_type: "tv", tmdb_id: 7, seasons: [0] }]);
});

test.each([
	{
		name: "Standard",
		initial: BOTH,
		refreshed: { ...BOTH, can_request_standard: false },
		button: "Request",
		value: "standard",
	},
	{
		name: "4K",
		initial: { ...BOTH, can_request_standard: false },
		refreshed: { ...BOTH, can_request_4k: false },
		button: "Request 4K",
		value: "4k",
	},
])("picker keeps its implicit $name variant when that permission disappears", async ({
	name,
	initial,
	refreshed,
	button,
	value,
}) => {
	const { bodies } = fixture(initial);
	const client = renderTv();
	fireEvent.click(await screen.findByRole("button", { name: button }));
	screen.getByRole("dialog", { name: "Choose seasons" });
	act(() => client.setQueryData(["destinations", "tv"], refreshed));
	await waitFor(() =>
		expect(
			(screen.getByRole("option", { name }) as HTMLOptionElement).disabled,
		).toBe(true),
	);
	await act(async () => {
		fireEvent.click(screen.getByRole("button", { name: "OK" }));
	});
	expect(bodies).toEqual([]);
	expect(
		(screen.getByRole("combobox", { name: "Quality" }) as HTMLSelectElement)
			.value,
	).toBe(value);
});

test.each([
	{ ...OPTIONS, can_request_partial: false },
	{ ...OPTIONS, available: false, can_request_partial: false },
])("disabled or unknown partial policy skips the picker and preserves whole-series requests", async (options) => {
	const { bodies } = fixture(options);
	renderTv();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	await screen.findByText("Requested ✓");
	expect(screen.queryByRole("dialog")).toBeNull();
	expect(bodies).toEqual([{ media_type: "tv", tmdb_id: 7 }]);
});

test("partial policy disabled leaves sole Specials to the Seerr fallback", async () => {
	const { bodies } = fixture(
		{ ...OPTIONS, can_request_partial: false },
		{
			status: "failed",
			seerr_url: "https://requests.example/tv/7",
		},
	);
	renderTv([SEASONS[0], { ...SEASONS[1], episode_count: 0 }]);
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	await screen.findByRole("link", { name: "Request in Seerr ↗" });
	expect(screen.queryByRole("dialog")).toBeNull();
	expect(bodies).toEqual([{ media_type: "tv", tmdb_id: 7 }]);
});

test.each([
	false,
	true,
])("partial policy loss blocks an open picker's default or subset (%s)", async (subset) => {
	const { bodies } = fixture();
	const client = renderTv();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	if (subset) fireEvent.click(toggle(/Season 1/));
	act(() =>
		client.setQueryData(["destinations", "tv"], {
			...OPTIONS,
			can_request_partial: false,
			can_request_specials: false,
		}),
	);
	await waitFor(() =>
		expect(screen.queryByRole("switch", { name: /Specials/ })).toBeNull(),
	);
	await act(async () => {
		fireEvent.click(screen.getByRole("button", { name: "OK" }));
	});
	expect(bodies).toEqual([]);
	fireEvent.click(screen.getByRole("button", { name: "Request" }));
	await screen.findByText("Requested ✓");
	expect(screen.queryByRole("dialog")).toBeNull();
	expect(bodies).toEqual([{ media_type: "tv", tmdb_id: 7 }]);
});

test.each([
	"Cancel",
	"Escape",
])("Standard-only requests keep Quality hidden while picking and after %s", async (action) => {
	const { bodies } = fixture();
	renderTv();
	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	screen.getByRole("dialog", { name: "Choose seasons" });
	expect(screen.queryByRole("combobox", { name: "Quality" })).toBeNull();
	if (action === "Escape") fireEvent.keyDown(document, { key: "Escape" });
	else fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
	expect(screen.queryByRole("dialog")).toBeNull();
	expect(screen.queryByRole("combobox", { name: "Quality" })).toBeNull();
	expect(bodies).toEqual([]);
});
