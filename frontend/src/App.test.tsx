import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

const USER = {
	id: 1,
	display_name: "Viewer",
	avatar_url: null,
	is_admin: false,
};
const HEALTH = { status: "ok", tmdb_configured: false, seerr_configured: true };

function renderApp() {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={queryClient}>
			<App />
		</QueryClientProvider>,
	);
}

test("unauthenticated visitors see the login screen only", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL) => {
			expect(String(input)).toBe("/api/v1/auth/me");
			return {
				ok: false,
				status: 401,
				json: async () => ({ detail: "Not authenticated" }),
			} as Response;
		}),
	);

	renderApp();

	expect(
		await screen.findByRole("button", { name: "Sign in with Plex" }),
	).toBeTruthy();
	expect(screen.queryByText(/Signed in as/)).toBeNull();
});

test("authenticated users see the shell with their name and health", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			const body = url === "/api/v1/auth/me" ? USER : HEALTH;
			return { ok: true, status: 200, json: async () => body } as Response;
		}),
	);

	renderApp();

	expect(await screen.findByText("Viewer")).toBeTruthy();
	expect(await screen.findByText("ok")).toBeTruthy();
	expect(
		screen.queryByRole("button", { name: "Sign in with Plex" }),
	).toBeNull();
});

test("logout returns to the login screen", async () => {
	let signedIn = true;
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = String(input);
			if (url === "/api/v1/auth/logout") {
				expect(init?.method).toBe("POST");
				signedIn = false;
				return { ok: true, status: 204, json: async () => null } as Response;
			}
			if (url === "/api/v1/auth/me") {
				return signedIn
					? ({ ok: true, status: 200, json: async () => USER } as Response)
					: ({
							ok: false,
							status: 401,
							json: async () => ({ detail: "Not authenticated" }),
						} as Response);
			}
			return { ok: true, status: 200, json: async () => HEALTH } as Response;
		}),
	);

	renderApp();

	fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));

	expect(
		await screen.findByRole("button", { name: "Sign in with Plex" }),
	).toBeTruthy();
});
