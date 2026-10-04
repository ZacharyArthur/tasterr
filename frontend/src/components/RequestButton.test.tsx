import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { Availability } from "../lib/api";
import { RequestButton } from "./RequestButton";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

function av(status: Availability["status"], known = true): Availability {
	return { status, known };
}

/** Route fetches by URL substring; unmatched paths 404. Returns the mock. */
function stubFetch(routes: Record<string, unknown>) {
	const mock = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		for (const [path, body] of Object.entries(routes)) {
			if (url.includes(path)) {
				return { ok: true, status: 200, json: async () => body } as Response;
			}
		}
		return {
			ok: false,
			status: 404,
			json: async () => ({ detail: "x" }),
		} as Response;
	});
	vi.stubGlobal("fetch", mock);
	return mock;
}

function renderButton(availability?: Availability | null) {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={queryClient}>
			<RequestButton type="movie" id={42} availability={availability} />
		</QueryClientProvider>,
	);
}

const SEERR_ON = { tmdb_configured: true, seerr_configured: true };
const SEERR_OFF = { tmdb_configured: true, seerr_configured: false };

test("submits a request through the client and confirms success", async () => {
	stubFetch({
		"/api/v1/config": SEERR_ON,
		"/api/v1/request": {
			status: "ok",
			availability: av("pending"),
			seerr_url: "https://requests.example/movie/42",
		},
	});
	renderButton(av("not_requested"));

	fireEvent.click(await screen.findByRole("button", { name: "Request" }));

	expect(await screen.findByText("Requested ✓")).toBeTruthy();
});

test("prompts re-login when the backend signals re_auth_required", async () => {
	stubFetch({
		"/api/v1/config": SEERR_ON,
		"/api/v1/request": {
			status: "re_auth_required",
			availability: null,
			seerr_url: null,
		},
	});
	renderButton(av("not_requested"));

	fireEvent.click(await screen.findByRole("button", { name: "Request" }));

	const alert = await screen.findByRole("alert");
	expect(alert.textContent).toContain("sign in again");
});

test("offers the server-built Seerr fallback link on failure", async () => {
	stubFetch({
		"/api/v1/config": SEERR_ON,
		"/api/v1/request": {
			status: "failed",
			availability: null,
			seerr_url: "https://requests.example/movie/42",
		},
	});
	renderButton(av("not_requested"));

	fireEvent.click(await screen.findByRole("button", { name: "Request" }));

	const link = await screen.findByRole("link", { name: /Request in Seerr/ });
	expect(link.getAttribute("href")).toBe("https://requests.example/movie/42");
});

test("renders no affordance when Seerr is unconfigured", async () => {
	const mock = stubFetch({ "/api/v1/config": SEERR_OFF });
	renderButton(av("not_requested"));

	await waitFor(() => expect(mock).toHaveBeenCalled()); // config resolved
	expect(screen.queryByRole("button")).toBeNull();
});

test("shows no request button when the title is already available", async () => {
	stubFetch({ "/api/v1/request": {}, "/api/v1/config": SEERR_ON });
	renderButton(av("available"));

	await waitFor(() =>
		expect(screen.queryByRole("button", { name: "Request" })).toBeNull(),
	);
});

// ── Destination override (request-destination-override) ─────────────────────

const ONE_DESTINATION = [
	{
		server_id: 0,
		server_name: "radarr",
		is_default: true,
		default_profile_id: 7,
		default_root_folder: "/movies",
		quality_profiles: [{ id: 7, name: "HD Bluray + WEB" }],
		root_folders: [{ id: 1, path: "/movies" }],
	},
];
const TWO_DESTINATIONS = [
	...ONE_DESTINATION,
	{
		server_id: 1,
		server_name: "radarr (new releases)",
		is_default: false,
		default_profile_id: 4,
		default_root_folder: "/new releases",
		quality_profiles: [
			{ id: 7, name: "HD Bluray + WEB" },
			{ id: 4, name: "HD-1080p" },
		],
		root_folders: [
			{ id: 1, path: "/movies" },
			{ id: 2, path: "/new releases" },
		],
	},
];

test("a single destination with no other options requests immediately", async () => {
	stubFetch({
		"/api/v1/config": SEERR_ON,
		"/destinations": ONE_DESTINATION,
		"/api/v1/request": {
			status: "ok",
			availability: av("pending"),
			seerr_url: null,
		},
	});
	renderButton(av("not_requested"));

	fireEvent.click(await screen.findByRole("button", { name: "Request" }));

	await screen.findByText("Requested ✓");
	expect(screen.queryByText("Root Folder")).toBeNull();
});

test("clicking Request opens the picker for a single server with multiple root folders", async () => {
	const oneServerManyFolders = [
		{
			...ONE_DESTINATION[0],
			root_folders: [
				{ id: 1, path: "/movies" },
				{ id: 2, path: "/new releases" },
				{ id: 3, path: "/comedy specials" },
			],
		},
	];
	stubFetch({
		"/api/v1/config": SEERR_ON,
		"/destinations": oneServerManyFolders,
	});
	renderButton(av("not_requested"));

	const button = await screen.findByRole("button", { name: "Request" });
	expect(screen.queryByText("Root Folder")).toBeNull();

	fireEvent.click(button);

	expect(await screen.findByText("Root Folder")).toBeTruthy();
	expect(screen.getByRole("combobox", { name: "Server" })).toBeTruthy();
	expect(screen.getByRole("button", { name: "Confirm request" })).toBeTruthy();
});

test("clicking Request opens the picker for multiple destinations", async () => {
	stubFetch({
		"/api/v1/config": SEERR_ON,
		"/destinations": TWO_DESTINATIONS,
	});
	renderButton(av("not_requested"));

	const button = await screen.findByRole("button", { name: "Request" });
	expect(screen.queryByText("Root Folder")).toBeNull();

	fireEvent.click(button);

	expect(await screen.findByText("Root Folder")).toBeTruthy();
	expect(screen.getByRole("combobox", { name: "Server" })).toBeTruthy();
});

test("confirming the picker sends the selected destination", async () => {
	const requestCalls: unknown[] = [];
	const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
		const url = String(input);
		if (url.includes("/api/v1/request")) {
			requestCalls.push(init?.body ? JSON.parse(String(init.body)) : null);
			return {
				ok: true,
				status: 200,
				json: async () => ({
					status: "ok",
					availability: av("pending"),
					seerr_url: null,
				}),
			} as Response;
		}
		if (url.includes("/destinations")) {
			return {
				ok: true,
				status: 200,
				json: async () => TWO_DESTINATIONS,
			} as Response;
		}
		if (url.includes("/api/v1/config")) {
			return { ok: true, status: 200, json: async () => SEERR_ON } as Response;
		}
		return {
			ok: false,
			status: 404,
			json: async () => ({ detail: "x" }),
		} as Response;
	});
	vi.stubGlobal("fetch", mock);
	renderButton(av("not_requested"));

	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	const serverSelect = await screen.findByRole("combobox", { name: "Server" });
	fireEvent.change(serverSelect, { target: { value: "1" } });
	fireEvent.click(screen.getByRole("button", { name: "Confirm request" }));

	await screen.findByText("Requested ✓");
	expect(requestCalls).toEqual([
		{
			media_type: "movie",
			tmdb_id: 42,
			server_id: 1,
			profile_id: 4,
			root_folder: "/new releases",
		},
	]);
});

test("confirming the picker without changing the selection sends the default destination", async () => {
	const requestCalls: unknown[] = [];
	const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
		const url = String(input);
		if (url.includes("/api/v1/request")) {
			requestCalls.push(init?.body ? JSON.parse(String(init.body)) : null);
			return {
				ok: true,
				status: 200,
				json: async () => ({
					status: "ok",
					availability: av("pending"),
					seerr_url: null,
				}),
			} as Response;
		}
		if (url.includes("/destinations")) {
			return {
				ok: true,
				status: 200,
				json: async () => TWO_DESTINATIONS,
			} as Response;
		}
		if (url.includes("/api/v1/config")) {
			return { ok: true, status: 200, json: async () => SEERR_ON } as Response;
		}
		return {
			ok: false,
			status: 404,
			json: async () => ({ detail: "x" }),
		} as Response;
	});
	vi.stubGlobal("fetch", mock);
	renderButton(av("not_requested"));

	fireEvent.click(await screen.findByRole("button", { name: "Request" }));
	fireEvent.click(
		await screen.findByRole("button", { name: "Confirm request" }),
	);

	await screen.findByText("Requested ✓");
	expect(requestCalls).toEqual([
		{
			media_type: "movie",
			tmdb_id: 42,
			server_id: 0,
			profile_id: 7,
			root_folder: "/movies",
		},
	]);
});
