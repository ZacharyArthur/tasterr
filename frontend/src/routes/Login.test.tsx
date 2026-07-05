import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ME_QUERY_KEY } from "../lib/auth";
import { Login } from "./Login";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

type Route = (init?: RequestInit) => { status: number; body: unknown };

function stubFetch(routes: Record<string, Route>) {
	const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
		const route = routes[String(input)];
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

test("plex flow: opens approval url, polls, refreshes auth state", async () => {
	stubFetch({
		"/api/v1/auth/plex/pin": () => ({
			status: 200,
			body: {
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			},
		}),
		"/api/v1/auth/plex/pin/opaque-handle": () => ({
			status: 200,
			body: { status: "ok", user: USER },
		}),
	});
	const open = vi.fn();
	vi.stubGlobal("open", open);
	const invalidate = renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Sign in with Plex" }));

	await screen.findByText("Waiting for Plex approval…");
	expect(open).toHaveBeenCalledWith(
		"https://app.plex.tv/auth#?x",
		"_blank",
		"noopener",
	);
	await vi.waitFor(() => {
		expect(invalidate).toHaveBeenCalledWith({ queryKey: ME_QUERY_KEY });
	});
});

test("plex flow: expired handle surfaces a retry message", async () => {
	stubFetch({
		"/api/v1/auth/plex/pin": () => ({
			status: 200,
			body: {
				pin_id: "opaque-handle",
				auth_url: "https://app.plex.tv/auth#?x",
			},
		}),
		"/api/v1/auth/plex/pin/opaque-handle": () => ({
			status: 404,
			body: { detail: "Unknown or expired sign-in attempt" },
		}),
	});
	vi.stubGlobal("open", vi.fn());
	renderLogin();

	fireEvent.click(screen.getByRole("button", { name: "Sign in with Plex" }));

	expect(
		await screen.findByText("Plex sign-in expired — try again."),
	).toBeTruthy();
	// The button is armed again for a fresh attempt.
	expect(
		screen.getByRole("button", { name: "Sign in with Plex" }),
	).toBeTruthy();
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
