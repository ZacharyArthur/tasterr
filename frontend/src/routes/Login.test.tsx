import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ME_QUERY_KEY } from "../lib/auth";
import { Login } from "./Login";

beforeEach(() => {
	vi.spyOn(window, "focus").mockImplementation(() => undefined);
});

afterEach(() => {
	cleanup();
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

type Route = (init?: RequestInit) => { status: number; body: unknown };

function stubFetch(routes: Record<string, Route>) {
	const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
		// Key POSTs by URL + method so the Plex poll (POST /pin/poll) is distinct
		// from the Plex create (POST /pin) under the same path prefix.
		const method = init?.method ?? "GET";
		const key = `${method} ${String(input)}`;
		const route = routes[key] ?? routes[String(input)];
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

function renderLogin() {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	const invalidate = vi.spyOn(queryClient, "invalidateQueries");
	render(
		<QueryClientProvider client={queryClient}>
			<Login />
		</QueryClientProvider>,
	);
	return invalidate;
}

const USER = {
	id: 1,
	display_name: "Viewer",
	avatar_url: null,
	is_admin: false,
};

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
	const parentFocus = vi.mocked(window.focus);
	const invalidate = renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Sign in with Plex" }));

	await screen.findByText("Waiting for Plex approval…");
	expect(open).toHaveBeenCalledWith(
		"",
		"tasterr-plex-auth",
		"popup=yes,width=600,height=700,scrollbars=yes,resizable=yes",
	);
	expect(approval.opener).toBeNull();
	expect(focus).toHaveBeenCalledOnce();
	expect(replace).toHaveBeenCalledWith("https://app.plex.tv/auth#?x");
	// First poll answers pending; the 2s refetch interval must fire again.
	await vi.waitFor(() => expect(polls).toBeGreaterThanOrEqual(2), {
		timeout: 5000,
		interval: 100,
	});
	await vi.waitFor(
		() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ME_QUERY_KEY }),
		{ timeout: 5000 },
	);
	expect(close).toHaveBeenCalledOnce();
	expect(parentFocus).toHaveBeenCalledOnce();
}, 15000);

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
	renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Sign in with Plex" }));

	expect(
		await screen.findByText("Plex sign-in expired — try again."),
	).toBeTruthy();
	// The button is armed again for a fresh attempt.
	expect(
		screen.getByRole("button", { name: "Sign in with Plex" }),
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
	renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Sign in with Plex" }));

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
	const invalidate = renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Sign in with Plex" }));

	await vi.waitFor(() =>
		expect(invalidate).toHaveBeenCalledWith({ queryKey: ME_QUERY_KEY }),
	);
});

test("plex flow reopens a protected approval window after popup blocking", async () => {
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
	const { approval, close, replace } = fakeApprovalWindow();
	const open = vi
		.fn<() => Window | null>()
		.mockReturnValueOnce(null)
		.mockReturnValueOnce(approval);
	vi.stubGlobal("open", open);
	renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Sign in with Plex" }));
	fireEvent.click(
		await screen.findByRole("button", { name: "Reopen the approval page" }),
	);

	expect(open).toHaveBeenNthCalledWith(
		2,
		"",
		"tasterr-plex-auth",
		"popup=yes,width=600,height=700,scrollbars=yes,resizable=yes",
	);
	expect(approval.opener).toBeNull();
	expect(replace).toHaveBeenCalledWith("https://app.plex.tv/auth#?x");
	cleanup();
	expect(close).toHaveBeenCalledOnce();
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
	const invalidate = renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Sign in with Plex" }));

	await vi.waitFor(() =>
		expect(invalidate).toHaveBeenCalledWith({ queryKey: ME_QUERY_KEY }),
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
	const invalidate = renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Sign in with Plex" }));

	await vi.waitFor(() =>
		expect(invalidate).toHaveBeenCalledWith({ queryKey: ME_QUERY_KEY }),
	);
	expect(approval.location.replace).not.toHaveBeenCalled();
});

test("local login posts credentials and refreshes auth state", async () => {
	const mock = stubFetch({
		"/api/v1/auth/local": () => ({ status: 200, body: USER }),
	});
	const invalidate = renderLogin();

	fireEvent.change(screen.getByLabelText("Email"), {
		target: { value: "a@b.c" },
	});
	fireEvent.change(screen.getByLabelText("Password"), {
		target: { value: "pw" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

	await vi.waitFor(() => {
		expect(invalidate).toHaveBeenCalledWith({ queryKey: ME_QUERY_KEY });
	});
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
	renderLogin();

	fireEvent.change(screen.getByLabelText("Email"), {
		target: { value: "a@b.c" },
	});
	fireEvent.change(screen.getByLabelText("Password"), {
		target: { value: "wrong" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

	expect(await screen.findByText("Invalid email or password")).toBeTruthy();
});
