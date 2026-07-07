import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
const HOME = {
	hero: [],
	rails: [
		{ id: "trending", title: "Trending Now", kind: "standard", items: [] },
	],
};
const RAILS = { rails: [], next_cursor: null };

function jsonResponse(body: unknown, status = 200): Response {
	return { ok: status < 400, status, json: async () => body } as Response;
}

function renderApp() {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={queryClient}>
			<MemoryRouter>
				<App />
			</MemoryRouter>
		</QueryClientProvider>,
	);
}

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
