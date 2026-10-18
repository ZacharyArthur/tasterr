import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	act,
	cleanup,
	fireEvent,
	render,
	screen,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ME_QUERY_KEY, setConfirmedSession } from "../lib/auth";
import { Login } from "./Login";

beforeEach(() => {
	vi.spyOn(window, "focus").mockImplementation(() => undefined);
});

afterEach(() => {
	cleanup();
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
	Reflect.deleteProperty(document, "execCommand");
});

type Route = (init?: RequestInit) => { status: number; body: unknown };

function stubFetch(routes: Record<string, Route>) {
	const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
		// Key POSTs by URL + method so the Plex poll (POST /pin/poll) is distinct
		// from the Plex create (POST /pin) under the same path prefix.
		const method = init?.method ?? "GET";
		const key = `${method} ${String(input)}`;
		const route =
			routes[key] ??
			routes[String(input)] ??
			(key === "GET /api/v1/auth/methods"
				? () => ({
						status: 200,
						body: { plex: true, jellyfin: true, seerr: true },
					})
				: undefined);
		if (route === undefined) {
			throw new Error(`unexpected fetch: ${String(input)}`);
		}
		const result = route(init);
		return {
			ok: result.status >= 200 && result.status < 300,
			status: result.status,
			json: async () => result.body,
		} as Response;
	});
	vi.stubGlobal("fetch", mock);
	return mock;
}

async function renderLogin(
	queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	}),
) {
	render(
		<QueryClientProvider client={queryClient}>
			<Login />
		</QueryClientProvider>,
	);
	await vi.waitFor(() =>
		expect(queryClient.getQueryState(["auth", "methods"])?.status).toBe(
			"success",
		),
	);
	return queryClient;
}

const USER = {
	id: 1,
	display_name: "Viewer",
	avatar_url: null,
	is_admin: false,
};

test.each([
	{ plex: true, jellyfin: false, seerr: false },
	{ plex: false, jellyfin: true, seerr: false },
	{ plex: false, jellyfin: false, seerr: true },
	{ plex: true, jellyfin: true, seerr: true },
	{ plex: false, jellyfin: false, seerr: false },
])("shows only available methods: %j", async (methods) => {
	const fetch = stubFetch({
		"GET /api/v1/auth/methods": () => ({ status: 200, body: methods }),
	});
	await renderLogin();
	expect(
		Boolean(screen.queryByRole("button", { name: "Continue with Plex" })),
	).toBe(methods.plex);
	expect(
		Boolean(screen.queryByRole("button", { name: "Continue with Seerr" })),
	).toBe(methods.seerr);
	expect(
		Boolean(screen.queryByRole("button", { name: "Continue with Jellyfin" })),
	).toBe(methods.jellyfin);
	expect(screen.queryByLabelText("Email")).toBeNull();
	if (!methods.plex && !methods.jellyfin && !methods.seerr)
		expect(screen.getByRole("alert").textContent).toBe(
			"Sign-in is currently unavailable.",
		);
	expect(fetch).toHaveBeenCalledOnce();
});

test("Seerr form expands and collapses in place", async () => {
	stubFetch({});
	await renderLogin();
	const button = screen.getByRole("button", { name: "Continue with Seerr" });
	expect(button.getAttribute("aria-expanded")).toBe("false");
	expect(screen.queryByLabelText("Email")).toBeNull();
	fireEvent.click(button);
	expect(button.getAttribute("aria-expanded")).toBe("true");
	expect(screen.getByLabelText("Email")).toBeTruthy();
	expect(screen.getByLabelText("Password")).toBeTruthy();
	fireEvent.click(button);
	expect(button.getAttribute("aria-expanded")).toBe("false");
	expect(screen.queryByLabelText("Email")).toBeNull();
});

function fakeApprovalWindow(closed = false) {
	const close = vi.fn();
	const focus = vi.fn();
	const replace = vi.fn();
	const approval = {
		closed,
		close,
		focus,
		opener: window,
		location: { replace },
	} as unknown as Window;
	return { approval, close, focus, replace };
}

test("plex flow protects and closes its approval window after polling succeeds", async () => {
	let polls = 0;
	stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({
			status: 200,
			body: {
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			},
		}),
		"POST /api/v1/auth/plex/pin/poll": () => {
			polls += 1;
			return polls === 1
				? { status: 200, body: { status: "pending", user: null } }
				: { status: 200, body: { status: "ok", user: USER } };
		},
	});
	const { approval, close, focus, replace } = fakeApprovalWindow();
	const open = vi.fn(() => approval);
	vi.stubGlobal("open", open);
	const writeText = vi.fn(() => Promise.resolve());
	vi.stubGlobal("navigator", { clipboard: { writeText } });
	const parentFocus = vi.mocked(window.focus);
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	queryClient.setQueryData(["title", "movie", 7], { owner: "A" });
	await renderLogin(queryClient);

	fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));

	await screen.findByText("Waiting for Plex approval…");
	const approvalLink = screen.getByRole("link", {
		name: "Open the approval page",
	}) as HTMLAnchorElement;
	expect(approvalLink.target).toBe("_blank");
	expect(approvalLink.rel).toBe("noopener noreferrer");
	expect(open).toHaveBeenCalledWith(
		"",
		"_blank",
		expect.stringMatching(/^width=600,height=700,left=-?\d+,top=-?\d+$/),
	);
	expect(approval.opener).toBeNull();
	expect(focus).toHaveBeenCalledOnce();
	expect(replace).toHaveBeenCalledWith("https://app.plex.tv/auth#?x");
	fireEvent.click(screen.getByRole("button", { name: "Copy approval URL" }));
	expect(await screen.findByText("Approval URL copied.")).toBeTruthy();
	expect(writeText).toHaveBeenCalledWith("https://app.plex.tv/auth#?x");
	// First poll answers pending; the 2s refetch interval must fire again.
	await vi.waitFor(() => expect(polls).toBeGreaterThanOrEqual(2), {
		timeout: 5000,
		interval: 100,
	});
	await vi.waitFor(
		() => expect(queryClient.getQueryData(ME_QUERY_KEY)).toEqual(USER),
		{ timeout: 5000 },
	);
	expect(close).toHaveBeenCalledOnce();
	expect(parentFocus).toHaveBeenCalledOnce();
	expect(queryClient.getQueryData(["title", "movie", 7])).toBeUndefined();
	expect(
		queryClient.getQueriesData({ queryKey: ["auth", "plex-pin"] }),
	).toEqual([]);
	expect(queryClient.getMutationCache().getAll()).toEqual([]);
}, 15000);

test("plex flow rejects a completed poll without a user", async () => {
	stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({
			status: 200,
			body: {
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			},
		}),
		"POST /api/v1/auth/plex/pin/poll": () => ({
			status: 200,
			body: { status: "ok", user: null },
		}),
	});
	const { approval, close } = fakeApprovalWindow();
	vi.stubGlobal(
		"open",
		vi.fn(() => approval),
	);
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	queryClient.setQueryData(["pre-login"], "keep");
	await renderLogin(queryClient);

	fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));

	expect(
		await screen.findByText("Plex sign-in failed — try again."),
	).toBeTruthy();
	expect(close).toHaveBeenCalledOnce();
	expect(queryClient.getQueryData(["pre-login"])).toBe("keep");
	expect(queryClient.getQueryData(ME_QUERY_KEY)).toBeUndefined();
	expect(
		(
			screen.getByRole("button", {
				name: "Continue with Plex",
			}) as HTMLButtonElement
		).disabled,
	).toBe(false);
});

test("plex flow: expired handle surfaces a retry message", async () => {
	stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({
			status: 200,
			body: {
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			},
		}),
		"POST /api/v1/auth/plex/pin/poll": () => ({
			status: 404,
			body: { detail: "Unknown or expired sign-in attempt" },
		}),
	});
	const { approval, close } = fakeApprovalWindow();
	vi.stubGlobal(
		"open",
		vi.fn(() => approval),
	);
	await renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));

	expect(
		await screen.findByText("Plex sign-in expired — try again."),
	).toBeTruthy();
	// The button is armed again for a fresh attempt.
	expect(
		screen.getByRole("button", { name: "Continue with Plex" }),
	).toBeTruthy();
	expect(close).toHaveBeenCalledOnce();
});

test("plex flow closes its blank window when PIN creation fails", async () => {
	stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({ status: 503, body: {} }),
	});
	const { approval, close } = fakeApprovalWindow();
	vi.stubGlobal(
		"open",
		vi.fn(() => approval),
	);
	await renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));

	expect(
		await screen.findByText("Could not reach Plex — try again."),
	).toBeTruthy();
	expect(close).toHaveBeenCalledOnce();
});

test("plex flow can complete when the approval window is blocked", async () => {
	stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({
			status: 200,
			body: {
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			},
		}),
		"POST /api/v1/auth/plex/pin/poll": () => ({
			status: 200,
			body: { status: "ok", user: USER },
		}),
	});
	vi.stubGlobal(
		"open",
		vi.fn(() => null),
	);
	const queryClient = await renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));

	await vi.waitFor(() =>
		expect(queryClient.getQueryData(ME_QUERY_KEY)).toEqual(USER),
	);
});

test("plex flow shows a reachable approval link after popup blocking", async () => {
	stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({
			status: 200,
			body: {
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			},
		}),
		"POST /api/v1/auth/plex/pin/poll": () => ({
			status: 200,
			body: { status: "pending", user: null },
		}),
	});
	vi.stubGlobal(
		"open",
		vi.fn(() => null),
	);
	vi.stubGlobal("navigator", {});
	const execCommand = vi.fn(() => {
		const textarea = document.activeElement as HTMLTextAreaElement;
		expect(textarea.value).toBe("https://app.plex.tv/auth#?x");
		expect(textarea.readOnly).toBe(true);
		expect(textarea.tabIndex).toBe(-1);
		expect(textarea.getAttribute("aria-hidden")).toBe("true");
		expect(textarea.style.position).toBe("fixed");
		expect(textarea.style.top).toBe("0px");
		expect(textarea.style.left).toBe("0px");
		return true;
	});
	Object.defineProperty(document, "execCommand", {
		configurable: true,
		value: execCommand,
	});
	await renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));

	const link = await screen.findByRole("link", { name: "open it here" });
	expect((link as HTMLAnchorElement).href).toBe("https://app.plex.tv/auth#?x");
	expect((link as HTMLAnchorElement).target).toBe("_blank");
	expect((link as HTMLAnchorElement).rel).toBe("noopener noreferrer");
	expect(
		screen
			.getByText(/The Plex window isn't available/)
			.closest("[aria-live]")
			?.getAttribute("aria-live"),
	).toBe("polite");
	const copyButton = screen.getByRole("button", {
		name: "Copy approval URL",
	});
	fireEvent.click(screen.getByRole("button", { name: "Continue with Seerr" }));
	const email = screen.getByLabelText("Email");
	email.focus();
	fireEvent.click(copyButton);
	expect(await screen.findByText("Approval URL copied.")).toBeTruthy();
	expect(execCommand).toHaveBeenCalledWith("copy");
	expect(document.activeElement).toBe(email);
	expect(document.querySelector('textarea[aria-hidden="true"]')).toBeNull();
});

test("plex flow re-announces repeated copy results", async () => {
	stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({
			status: 200,
			body: {
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			},
		}),
		"POST /api/v1/auth/plex/pin/poll": () => ({
			status: 200,
			body: { status: "pending", user: null },
		}),
	});
	vi.stubGlobal("navigator", {
		clipboard: { writeText: vi.fn(() => Promise.resolve()) },
	});
	const { approval } = fakeApprovalWindow();
	vi.stubGlobal(
		"open",
		vi.fn(() => approval),
	);
	await renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));
	const copyButton = await screen.findByRole("button", {
		name: "Copy approval URL",
	});
	fireEvent.click(copyButton);
	const firstAnnouncement = await screen.findByText("Approval URL copied.");
	fireEvent.click(copyButton);
	await vi.waitFor(() =>
		expect(screen.getByText("Approval URL copied.")).not.toBe(
			firstAnnouncement,
		),
	);
});

test("plex flow ignores copy feedback after the PIN expires", async () => {
	let polls = 0;
	let resolveCopy: () => void = () => undefined;
	stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({
			status: 200,
			body: {
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			},
		}),
		"POST /api/v1/auth/plex/pin/poll": () => {
			polls += 1;
			return polls === 1
				? { status: 200, body: { status: "pending", user: null } }
				: { status: 404, body: { detail: "expired" } };
		},
	});
	vi.stubGlobal("navigator", {
		clipboard: {
			writeText: vi.fn(
				() =>
					new Promise<void>((resolve) => {
						resolveCopy = () => resolve();
					}),
			),
		},
	});
	const { approval } = fakeApprovalWindow();
	vi.stubGlobal(
		"open",
		vi.fn(() => approval),
	);
	await renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));
	const copyButton = await screen.findByRole("button", {
		name: "Copy approval URL",
	});
	fireEvent.click(copyButton);
	expect(
		await screen.findByText("Plex sign-in expired — try again.", undefined, {
			timeout: 5000,
		}),
	).toBeTruthy();
	await act(async () => resolveCopy());

	expect(screen.queryByText("Approval URL copied.")).toBeNull();
	expect(
		screen.queryByText(
			"Could not copy the approval URL. Use the approval link instead.",
		),
	).toBeNull();
}, 10000);

test("plex flow reports when both clipboard paths fail", async () => {
	stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({
			status: 200,
			body: {
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			},
		}),
		"POST /api/v1/auth/plex/pin/poll": () => ({
			status: 200,
			body: { status: "pending", user: null },
		}),
	});
	vi.stubGlobal("navigator", {
		clipboard: { writeText: vi.fn(() => Promise.reject(new Error("denied"))) },
	});
	Object.defineProperty(document, "execCommand", {
		configurable: true,
		value: vi.fn(() => false),
	});
	vi.stubGlobal(
		"open",
		vi.fn(() => null),
	);
	await renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));
	const copyButton = await screen.findByRole("button", {
		name: "Copy approval URL",
	});
	fireEvent.click(screen.getByRole("button", { name: "Continue with Seerr" }));
	const email = screen.getByLabelText("Email");
	email.focus();
	const restoreFocus = vi.spyOn(email, "focus").mockImplementation(() => {
		throw new Error("focus blocked");
	});
	fireEvent.click(copyButton);

	expect(
		await screen.findByText(
			"Could not copy the approval URL. Use the approval link instead.",
		),
	).toBeTruthy();
	expect(restoreFocus).toHaveBeenCalledOnce();
});

test("plex flow centers the approval window in the current browser window", async () => {
	stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({ status: 503, body: {} }),
	});
	vi.spyOn(window, "screenX", "get").mockReturnValue(1400);
	vi.spyOn(window, "screenY", "get").mockReturnValue(100);
	vi.spyOn(window, "outerWidth", "get").mockReturnValue(1200);
	vi.spyOn(window, "outerHeight", "get").mockReturnValue(1000);
	const { approval } = fakeApprovalWindow();
	const open = vi.fn(() => approval);
	vi.stubGlobal("open", open);
	await renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));

	expect(open).toHaveBeenCalledWith(
		"",
		"_blank",
		"width=600,height=700,left=1700,top=250",
	);
	expect(
		await screen.findByText("Could not reach Plex — try again."),
	).toBeTruthy();
});

test("plex flow can complete after the user closes the approval window", async () => {
	stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({
			status: 200,
			body: {
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			},
		}),
		"POST /api/v1/auth/plex/pin/poll": () => ({
			status: 200,
			body: { status: "ok", user: USER },
		}),
	});
	const { approval, close, replace } = fakeApprovalWindow(true);
	vi.stubGlobal(
		"open",
		vi.fn(() => approval),
	);
	const queryClient = await renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));

	await vi.waitFor(() =>
		expect(queryClient.getQueryData(ME_QUERY_KEY)).toEqual(USER),
	);
	expect(replace).not.toHaveBeenCalled();
	expect(close).not.toHaveBeenCalled();
});

test("plex flow can complete when the browser severs the approval proxy", async () => {
	stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({
			status: 200,
			body: {
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			},
		}),
		"POST /api/v1/auth/plex/pin/poll": () => ({
			status: 200,
			body: { status: "ok", user: USER },
		}),
	});
	const approval = {
		get closed() {
			throw new DOMException("WindowProxy severed");
		},
		set opener(_value: Window | null) {
			throw new DOMException("WindowProxy severed");
		},
		close: vi.fn(),
		focus: vi.fn(),
		location: { replace: vi.fn() },
	} as unknown as Window;
	vi.stubGlobal(
		"open",
		vi.fn(() => approval),
	);
	const queryClient = await renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));

	await vi.waitFor(() =>
		expect(queryClient.getQueryData(ME_QUERY_KEY)).toEqual(USER),
	);
	expect(approval.location.replace).not.toHaveBeenCalled();
});

test("local login posts credentials and refreshes auth state", async () => {
	const mock = stubFetch({
		"/api/v1/auth/local": () => ({ status: 200, body: USER }),
	});
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	queryClient.setQueryData(["home"], { owner: "A" });
	await renderLogin(queryClient);

	fireEvent.click(screen.getByRole("button", { name: "Continue with Seerr" }));
	fireEvent.change(screen.getByLabelText("Email"), {
		target: { value: "a@b.c" },
	});
	fireEvent.change(screen.getByLabelText("Password"), {
		target: { value: "pw" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

	await vi.waitFor(() => {
		expect(queryClient.getQueryData(ME_QUERY_KEY)).toEqual(USER);
	});
	expect(queryClient.getQueryData(["home"])).toBeUndefined();
	expect(queryClient.getMutationCache().getAll()).toEqual([]);
	expect(mock).toHaveBeenCalledWith(
		"/api/v1/auth/local",
		expect.objectContaining({
			method: "POST",
			body: JSON.stringify({ email: "a@b.c", password: "pw" }),
		}),
	);
});

test("local login failure shows the generic backend message", async () => {
	stubFetch({
		"/api/v1/auth/local": () => ({
			status: 401,
			body: { detail: "Invalid email or password" },
		}),
	});
	await renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Continue with Seerr" }));
	fireEvent.change(screen.getByLabelText("Email"), {
		target: { value: "a@b.c" },
	});
	fireEvent.change(screen.getByLabelText("Password"), {
		target: { value: "wrong" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

	expect(await screen.findByText("Invalid email or password")).toBeTruthy();
});

test.each([
	"plex",
	"local",
	"jellyfin",
])("%s conflict shows server guidance and stops polling", async (method) => {
	const message =
		"Sign in with each account, keep one, delete the other, then link again.";
	const mock = stubFetch({
		"POST /api/v1/auth/plex/pin": () => ({
			status: 200,
			body: { pin_id: "conflict", auth_url: "https://app.plex.tv/auth" },
		}),
		"POST /api/v1/auth/plex/pin/poll": () => ({
			status: 409,
			body: { detail: message },
		}),
		"/api/v1/auth/local": () => ({ status: 409, body: { detail: message } }),
		"/api/v1/auth/jellyfin": () => ({ status: 409, body: { detail: message } }),
	});
	vi.stubGlobal("open", () => null);
	const cache = await renderLogin();
	if (method === "plex")
		fireEvent.click(screen.getByRole("button", { name: "Continue with Plex" }));
	else {
		fireEvent.click(
			screen.getByRole("button", {
				name:
					method === "jellyfin"
						? "Continue with Jellyfin"
						: "Continue with Seerr",
			}),
		);
		fireEvent.change(
			screen.getByLabelText(method === "jellyfin" ? "Username" : "Email"),
			{
				target: { value: "a@b.c" },
			},
		);
		fireEvent.change(screen.getByLabelText("Password"), {
			target: { value: "pw" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
	}
	expect(await screen.findByText(message)).toBeTruthy();
	expect(screen.queryByText("Waiting for Plex approval…")).toBeNull();
	expect(
		cache
			.getQueryCache()
			.findAll({ type: "active" })
			.some((query) => query.queryKey.includes("conflict")),
	).toBe(false);
	expect(
		mock.mock.calls.filter(([url]) => String(url).endsWith("/pin/poll")),
	).toHaveLength(method === "plex" ? 1 : 0);
});

test("Jellyfin form expands in place and resets cached session data on success", async () => {
	const fetch = stubFetch({
		"/api/v1/auth/jellyfin": () => ({ status: 200, body: USER }),
	});
	const cache = await renderLogin();
	cache.setQueryData(["home"], { owner: "prior" });
	fireEvent.click(
		screen.getByRole("button", { name: "Continue with Jellyfin" }),
	);
	fireEvent.change(screen.getByLabelText("Username"), {
		target: { value: "viewer" },
	});
	fireEvent.change(screen.getByLabelText("Password"), {
		target: { value: "pw" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
	await vi.waitFor(() =>
		expect(cache.getQueryData(ME_QUERY_KEY)).toEqual(USER),
	);
	expect(cache.getQueryData(["home"])).toBeUndefined();
	expect(cache.getMutationCache().getAll()).toEqual([]);
	expect(fetch).toHaveBeenCalledWith(
		"/api/v1/auth/jellyfin",
		expect.objectContaining({
			body: JSON.stringify({ username: "viewer", password: "pw" }),
		}),
	);
});

test("a late Jellyfin login cannot overwrite a newer confirmed session", async () => {
	let resolve!: (response: Response) => void;
	const pending = new Promise<Response>((done) => {
		resolve = done;
	});
	const fetch = vi.fn(async (input: RequestInfo | URL) =>
		String(input) === "/api/v1/auth/methods"
			? ({
					ok: true,
					status: 200,
					json: async () => ({ plex: false, jellyfin: true, seerr: false }),
				} as Response)
			: pending,
	);
	vi.stubGlobal("fetch", fetch);
	const cache = await renderLogin();
	fireEvent.click(
		screen.getByRole("button", { name: "Continue with Jellyfin" }),
	);
	fireEvent.change(screen.getByLabelText("Username"), {
		target: { value: "viewer" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
	await vi.waitFor(() =>
		expect(fetch).toHaveBeenCalledWith(
			"/api/v1/auth/jellyfin",
			expect.anything(),
		),
	);
	const newer = { ...USER, id: 2, display_name: "Other" };
	await setConfirmedSession(cache, newer);
	await act(async () => {
		resolve({ ok: true, status: 200, json: async () => USER } as Response);
		await pending;
	});
	expect(cache.getQueryData(ME_QUERY_KEY)).toEqual(newer);
});
