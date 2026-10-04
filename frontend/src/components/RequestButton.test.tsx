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
import type { Availability, RequestOptions } from "../lib/api";
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
