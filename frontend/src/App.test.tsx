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
import { App } from "./App";
import { setConfirmedSession } from "./lib/auth";

afterEach(() => {
	cleanup();
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

const USER = {
	id: 1,
	display_name: "Viewer",
	avatar_url: null,
	is_admin: false,
};
const USER_B = {
	id: 2,
	display_name: "Viewer B",
	avatar_url: null,
	is_admin: false,
};
const HOME = {
	hero: [],
	rails: [
		{ id: "trending", title: "Trending Now", kind: "standard", items: [] },
	],
};
const HOME_B = {
	hero: [],
	rails: [{ id: "for-b", title: "For Viewer B", kind: "standard", items: [] }],
};
const RAILS = { rails: [], next_cursor: null };
const CONFIG = {
	seerr_configured: false,
	plex_login_enabled: true,
	local_login_enabled: true,
	appearance: { theme: "dark", accent: "crimson" },
};

const USER_A_QUERY_DATA = [
	[["home"], HOME],
	[["rails"], { pages: [RAILS], pageParams: [0] }],
	[["title", "movie", 7], { owner: "A", watchlisted: true }],
	[["search", "private"], { owner: "A" }],
	[["config"], CONFIG],
	[["availability", ["movie:7"]], { owner: "A" }],
	[["explain", "movie", 7], { reasons: ["Viewer A's taste"] }],
	[["taste-onboarding", USER.id], { state: "done" }],
	[["household-members", USER.id], [{ id: USER.id, display_name: "Viewer A" }]],
	[["admin", "settings"], { owner: "A" }],
	[["admin", "regions"], { owner: "A" }],
	[["admin", "services", "US"], { owner: "A" }],
] as const;

function jsonResponse(body: unknown, status = 200): Response {
	return { ok: status < 400, status, json: async () => body } as Response;
}

function renderApp(
	initialEntry = "/",
	queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	}),
) {
	render(
		<QueryClientProvider client={queryClient}>
			<MemoryRouter initialEntries={[initialEntry]}>
				<App />
			</MemoryRouter>
		</QueryClientProvider>,
	);
	return queryClient;
}

function primeUserAQueries(queryClient: QueryClient) {
	queryClient.setQueryData(["auth", "me"], USER);
	for (const [queryKey, data] of USER_A_QUERY_DATA) {
		queryClient.setQueryData(queryKey, data);
	}
}

function expectUserAQueriesRemoved(queryClient: QueryClient) {
	for (const [queryKey] of USER_A_QUERY_DATA) {
		expect(queryClient.getQueryData(queryKey)).toBeUndefined();
	}
}

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((done) => {
		resolve = done;
	});
	return { promise, resolve };
}

test("a non-admin direct settings URL redirects before protected data is fetched", async () => {
	const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		if (url === "/api/v1/auth/me") return jsonResponse(USER);
		if (url === "/api/v1/home") return jsonResponse(HOME);
		if (url === "/api/v1/config")
			return jsonResponse({
				seerr_configured: false,
				plex_login_enabled: false,
				local_login_enabled: false,
				appearance: { theme: "dark", accent: "crimson" },
			});
		return jsonResponse(RAILS);
	});
	vi.stubGlobal("fetch", fetchMock);
	renderApp("/settings");
	expect(await screen.findByText("Trending Now")).toBeTruthy();
	expect(
		fetchMock.mock.calls.some(([url]) => String(url) === "/api/v1/settings"),
	).toBe(false);
});

test("authenticated shell applies only bounded appearance attributes", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url === "/api/v1/auth/me") return jsonResponse(USER);
			if (url === "/api/v1/home") return jsonResponse(HOME);
			if (url === "/api/v1/config")
				return jsonResponse({
					appearance: { theme: "light", accent: "azure" },
				});
			return jsonResponse(RAILS);
		}),
	);
	renderApp();
	const shell = (await screen.findByText("Trending Now")).closest(
		"[data-theme]",
	);
	expect(shell?.getAttribute("data-theme")).toBe("light");
	expect(shell?.getAttribute("data-accent")).toBe("azure");
	expect(localStorage.length).toBe(0);
});

test("unauthenticated visitors see the login screen only", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(async () => jsonResponse({ detail: "Not authenticated" }, 401)),
	);
	renderApp();
	expect(
		await screen.findByRole("button", { name: "Sign in with Plex" }),
	).toBeTruthy();
	expect(screen.queryByText("Sign out")).toBeNull();
});

test("authenticated users see the routed browse shell", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url === "/api/v1/auth/me") return jsonResponse(USER);
			if (url === "/api/v1/home") return jsonResponse(HOME);
			return jsonResponse(RAILS);
		}),
	);
	renderApp();
	expect(await screen.findByText("Viewer")).toBeTruthy();
	expect(await screen.findByText("Trending Now")).toBeTruthy();
	expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
	expect(screen.getByText(/not endorsed or certified/)).toBeTruthy(); // TMDB attribution
	expect(screen.getByRole("img", { name: "TMDB" })).toBeTruthy(); // TMDB logo
	expect(
		screen.queryByRole("button", { name: "Sign in with Plex" }),
	).toBeNull();
});

test("logout returns to the login screen", async () => {
	let signedIn = true;
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url === "/api/v1/auth/logout") {
				signedIn = false;
				return jsonResponse(null, 204);
			}
			if (url === "/api/v1/auth/me") {
				return signedIn
					? jsonResponse(USER)
					: jsonResponse({ detail: "no" }, 401);
			}
			if (url === "/api/v1/home") return jsonResponse(HOME);
			return jsonResponse(RAILS);
		}),
	);
	renderApp();
	fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
	expect(
		await screen.findByRole("button", { name: "Sign in with Plex" }),
	).toBeTruthy();
});

test("local account switch clears user A data and blocks a late query", async () => {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	primeUserAQueries(queryClient);
	const lateUserAHome = deferred<typeof HOME>();
	const lateUserACompleted = deferred<void>();
	const userBLogin = deferred<Response>();
	const userBHome = deferred<Response>();
	const lateRequest = queryClient
		.fetchQuery({
			queryKey: ["home"],
			queryFn: async () => {
				const home = await lateUserAHome.promise;
				lateUserACompleted.resolve(undefined);
				return home;
			},
		})
		.catch(() => undefined);
	expect(queryClient.getQueryState(["home"])?.fetchStatus).toBe("fetching");
	const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		if (url === "/api/v1/auth/logout") return jsonResponse(null, 204);
		if (url === "/api/v1/auth/local") return userBLogin.promise;
		if (url === "/api/v1/home") return userBHome.promise;
		if (url === "/api/v1/config") return jsonResponse(CONFIG);
		if (url === "/api/v1/rails?cursor=0") return jsonResponse(RAILS);
		if (url === "/api/v1/taste-onboarding")
			return jsonResponse({ state: "done" });
		throw new Error(`unexpected fetch: ${url}`);
	});
	vi.stubGlobal("fetch", fetchMock);
	renderApp("/", queryClient);

	const signOut = await screen.findByRole("button", { name: "Sign out" });
	expect(
		queryClient
			.getQueryCache()
			.find({ queryKey: ["home"] })
			?.getObserversCount(),
	).toBeGreaterThan(0);
	expect(queryClient.getQueryState(["home"])?.fetchStatus).toBe("fetching");
	fireEvent.click(signOut);
	await screen.findByRole("button", { name: "Sign in with Plex" });
	expectUserAQueriesRemoved(queryClient);
	expect(queryClient.getQueryData(["auth", "me"])).toBeNull();

	fireEvent.change(screen.getByLabelText("Email"), {
		target: { value: "viewer-b@example.test" },
	});
	fireEvent.change(screen.getByLabelText("Password"), {
		target: { value: "password" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
	await waitFor(() =>
		expect(fetchMock).toHaveBeenCalledWith(
			"/api/v1/auth/local",
			expect.objectContaining({ method: "POST" }),
		),
	);
	expectUserAQueriesRemoved(queryClient);
	expect(queryClient.getQueryData(["auth", "me"])).toBeNull();

	userBLogin.resolve(jsonResponse(USER_B));
	expect(await screen.findByText("Viewer B")).toBeTruthy();
	lateUserAHome.resolve({
		hero: [],
		rails: [
			{
				id: "private-a",
				title: "Viewer A Private",
				kind: "standard",
				items: [],
			},
		],
	});
	await lateUserACompleted.promise;
	await lateRequest;
	expect(queryClient.getQueryData(["home"])).toBeUndefined();
	expect(screen.queryByText("Viewer A Private")).toBeNull();

	userBHome.resolve(jsonResponse(HOME_B));
	expect(await screen.findByText("For Viewer B")).toBeTruthy();
});

test("Plex account switch clears user A data before user B arrives", async () => {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	primeUserAQueries(queryClient);
	const plexPoll = deferred<Response>();
	const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		if (url === "/api/v1/auth/logout") return jsonResponse(null, 204);
		if (url === "/api/v1/auth/plex/pin")
			return jsonResponse({
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			});
		if (url === "/api/v1/auth/plex/pin/poll") return plexPoll.promise;
		if (url === "/api/v1/home") return jsonResponse(HOME_B);
		if (url === "/api/v1/config") return jsonResponse(CONFIG);
		if (url === "/api/v1/rails?cursor=0") return jsonResponse(RAILS);
		if (url === "/api/v1/taste-onboarding")
			return jsonResponse({ state: "done" });
		throw new Error(`unexpected fetch: ${url}`);
	});
	vi.stubGlobal("fetch", fetchMock);
	vi.stubGlobal(
		"open",
		vi.fn(() => null),
	);
	vi.spyOn(window, "focus").mockImplementation(() => undefined);
	renderApp("/", queryClient);

	fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
	fireEvent.click(
		await screen.findByRole("button", { name: "Sign in with Plex" }),
	);
	await waitFor(() =>
		expect(fetchMock).toHaveBeenCalledWith(
			"/api/v1/auth/plex/pin/poll",
			expect.objectContaining({ method: "POST" }),
		),
	);
	expectUserAQueriesRemoved(queryClient);
	expect(queryClient.getQueryData(["auth", "me"])).toBeNull();

	plexPoll.resolve(jsonResponse({ status: "ok", user: USER_B }));
	expect(await screen.findByText("Viewer B")).toBeTruthy();
	expect(queryClient.getQueryData(["auth", "me"])).toEqual(USER_B);
});

test("initial and same-user auth resolutions preserve existing queries", async () => {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	queryClient.setQueryData(["before-auth"], { keep: true });
	let meReads = 0;
	const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		if (url === "/api/v1/auth/me") {
			meReads += 1;
			return jsonResponse(
				meReads === 1 ? USER : { ...USER, display_name: "Viewer refreshed" },
			);
		}
		if (url === "/api/v1/home") return jsonResponse(HOME);
		if (url === "/api/v1/config") return jsonResponse(CONFIG);
		if (url === "/api/v1/rails?cursor=0") return jsonResponse(RAILS);
		if (url === "/api/v1/taste-onboarding")
			return jsonResponse({ state: "done" });
		throw new Error(`unexpected fetch: ${url}`);
	});
	vi.stubGlobal("fetch", fetchMock);
	renderApp("/", queryClient);

	expect(await screen.findByText("Viewer")).toBeTruthy();
	expect(queryClient.getQueryData(["before-auth"])).toEqual({ keep: true });
	queryClient.setQueryData(["same-user"], { keep: true });

	await queryClient.refetchQueries({ queryKey: ["auth", "me"] });
	expect(await screen.findByText("Viewer refreshed")).toBeTruthy();
	expect(queryClient.getQueryData(["before-auth"])).toEqual({ keep: true });
	expect(queryClient.getQueryData(["same-user"])).toEqual({ keep: true });
});

test("a cancelled auth refresh cannot clear the newer session", async () => {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	const oldMe = deferred<Response>();
	const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		if (url === "/api/v1/auth/me") return oldMe.promise;
		if (url === "/api/v1/home") return jsonResponse(HOME_B);
		if (url === "/api/v1/config") return jsonResponse(CONFIG);
		if (url === "/api/v1/rails?cursor=0") return jsonResponse(RAILS);
		if (url === "/api/v1/taste-onboarding")
			return jsonResponse({ state: "done" });
		throw new Error(`unexpected fetch: ${url}`);
	});
	vi.stubGlobal("fetch", fetchMock);
	renderApp("/", queryClient);

	expect(await screen.findByText("Loading…")).toBeTruthy();
	await waitFor(() =>
		expect(fetchMock).toHaveBeenCalledWith("/api/v1/auth/me", undefined),
	);
	await setConfirmedSession(queryClient, USER_B);
	expect(await screen.findByText("Viewer B")).toBeTruthy();
	queryClient.setQueryData(["session-b"], { owner: "B" });

	oldMe.resolve(jsonResponse(USER));
	await new Promise((resolve) => setTimeout(resolve, 0));
	expect(queryClient.getQueryData(["auth", "me"])).toEqual(USER_B);
	expect(queryClient.getQueryData(["session-b"])).toEqual({ owner: "B" });
	expect(screen.getByText("Viewer B")).toBeTruthy();
});

test("auth refresh clears user A data before publishing user B", async () => {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	primeUserAQueries(queryClient);
	const userBMe = deferred<Response>();
	const userBHome = deferred<Response>();
	const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		if (url === "/api/v1/auth/me") return userBMe.promise;
		if (url === "/api/v1/home") return userBHome.promise;
		if (url === "/api/v1/config") return jsonResponse(CONFIG);
		if (url === "/api/v1/rails?cursor=0") return jsonResponse(RAILS);
		if (url === "/api/v1/taste-onboarding")
			return jsonResponse({ state: "done" });
		throw new Error(`unexpected fetch: ${url}`);
	});
	vi.stubGlobal("fetch", fetchMock);
	renderApp("/", queryClient);
	expect(await screen.findByText("Viewer")).toBeTruthy();
	expect(screen.getByText("Trending Now")).toBeTruthy();

	const refresh = queryClient.refetchQueries({ queryKey: ["auth", "me"] });
	await waitFor(() =>
		expect(fetchMock).toHaveBeenCalledWith("/api/v1/auth/me", undefined),
	);
	userBMe.resolve(jsonResponse(USER_B));
	await refresh;
	expect(await screen.findByText("Viewer B")).toBeTruthy();
	expect(queryClient.getQueryData(["home"])).toBeUndefined();
	expect(queryClient.getQueryData(["title", "movie", 7])).toBeUndefined();
	expect(queryClient.getQueryData(["explain", "movie", 7])).toBeUndefined();
	expect(
		queryClient.getQueryData(["taste-onboarding", USER.id]),
	).toBeUndefined();
	expect(queryClient.getQueryData(["admin", "settings"])).toBeUndefined();
	expect(screen.queryByText("Trending Now")).toBeNull();

	userBHome.resolve(jsonResponse(HOME_B));
	expect(await screen.findByText("For Viewer B")).toBeTruthy();
});

test("a late logout response cannot replace a newer confirmed user", async () => {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	primeUserAQueries(queryClient);
	const lateLogout = deferred<Response>();
	const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		if (url === "/api/v1/auth/logout") return lateLogout.promise;
		if (url === "/api/v1/auth/me")
			return jsonResponse({ detail: "Not authenticated" }, 401);
		if (url === "/api/v1/auth/local") return jsonResponse(USER_B);
		if (url === "/api/v1/home") return jsonResponse(HOME_B);
		if (url === "/api/v1/config") return jsonResponse(CONFIG);
		if (url === "/api/v1/rails?cursor=0") return jsonResponse(RAILS);
		if (url === "/api/v1/taste-onboarding")
			return jsonResponse({ state: "done" });
		throw new Error(`unexpected fetch: ${url}`);
	});
	vi.stubGlobal("fetch", fetchMock);
	renderApp("/", queryClient);

	fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
	await waitFor(() =>
		expect(fetchMock).toHaveBeenCalledWith(
			"/api/v1/auth/logout",
			expect.objectContaining({ method: "POST" }),
		),
	);
	await queryClient.refetchQueries({ queryKey: ["auth", "me"] });
	await screen.findByRole("button", { name: "Sign in with Plex" });

	fireEvent.change(screen.getByLabelText("Email"), {
		target: { value: "viewer-b@example.test" },
	});
	fireEvent.change(screen.getByLabelText("Password"), {
		target: { value: "password" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
	expect(await screen.findByText("Viewer B")).toBeTruthy();

	lateLogout.resolve(jsonResponse(null, 204));
	await new Promise((resolve) => setTimeout(resolve, 0));
	expect(queryClient.getQueryData(["auth", "me"])).toEqual(USER_B);
	expect(screen.getByText("Viewer B")).toBeTruthy();
	expect(
		screen.queryByRole("button", { name: "Sign in with Plex" }),
	).toBeNull();
});

test("failed logout preserves the confirmed session and its cache", async () => {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	primeUserAQueries(queryClient);
	const logoutFailure = deferred<Response>();
	const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		if (url === "/api/v1/auth/logout") return logoutFailure.promise;
		if (url === "/api/v1/taste-onboarding")
			return jsonResponse({ state: "done" });
		throw new Error(`unexpected fetch: ${url}`);
	});
	vi.stubGlobal("fetch", fetchMock);
	renderApp("/", queryClient);

	fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
	await waitFor(() =>
		expect(
			(screen.getByRole("button", { name: "Sign out" }) as HTMLButtonElement)
				.disabled,
		).toBe(true),
	);
	logoutFailure.resolve(jsonResponse({ detail: "Logout failed" }, 503));
	await waitFor(() =>
		expect(
			(screen.getByRole("button", { name: "Sign out" }) as HTMLButtonElement)
				.disabled,
		).toBe(false),
	);
	expect(queryClient.getQueryData(["auth", "me"])).toEqual(USER);
	expect(queryClient.getQueryData(["title", "movie", 7])).toEqual({
		owner: "A",
		watchlisted: true,
	});
	expect(screen.getByText("Viewer")).toBeTruthy();
});

test("failed local login preserves the confirmed signed-out state and cache", async () => {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	queryClient.setQueryData(["auth", "me"], null);
	queryClient.setQueryData(["pre-login"], "keep");
	vi.stubGlobal(
		"fetch",
		vi.fn(async () =>
			jsonResponse({ detail: "Invalid email or password" }, 401),
		),
	);
	renderApp("/", queryClient);

	fireEvent.change(screen.getByLabelText("Email"), {
		target: { value: "viewer-b@example.test" },
	});
	fireEvent.change(screen.getByLabelText("Password"), {
		target: { value: "wrong" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

	expect(await screen.findByText("Invalid email or password")).toBeTruthy();
	expect(queryClient.getQueryData(["auth", "me"])).toBeNull();
	expect(queryClient.getQueryData(["pre-login"])).toBe("keep");
});
