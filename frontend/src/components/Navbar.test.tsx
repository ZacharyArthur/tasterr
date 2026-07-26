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
import type { User } from "../lib/api";
import { Navbar } from "./Navbar";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

const USER: User = {
	id: 1,
	display_name: "Viewer",
	avatar_url: null,
	is_admin: false,
};

function stubFetch() {
	const mock = vi.fn(
		async (_input: RequestInfo | URL, _init?: RequestInit) =>
			({
				ok: true,
				status: 200,
				json: async () => ({ seeded_signals: 2 }),
			}) as Response,
	);
	vi.stubGlobal("fetch", mock);
	return mock;
}

function renderNavbar(user = USER) {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	queryClient.setQueryData(["home"], { hero: [], rails: [] });
	render(
		<QueryClientProvider client={queryClient}>
			<MemoryRouter>
				<Navbar user={user} />
			</MemoryRouter>
		</QueryClientProvider>,
	);
	return queryClient;
}

function openMenuAndReset() {
	fireEvent.click(screen.getByRole("button", { name: "Viewer" }));
	fireEvent.click(
		screen.getByRole("menuitem", { name: "Reset recommendations" }),
	);
}

test("reset stays put until the user confirms", () => {
	const fetchMock = stubFetch();
	vi.stubGlobal(
		"confirm",
		vi.fn(() => false),
	);
	renderNavbar();

	openMenuAndReset();

	expect(fetchMock).not.toHaveBeenCalled();
});

test("only admins receive the Settings menu entry", () => {
	stubFetch();
	renderNavbar();
	fireEvent.click(screen.getByRole("button", { name: "Viewer" }));
	expect(screen.queryByRole("menuitem", { name: "Settings" })).toBeNull();

	cleanup();
	renderNavbar({ ...USER, is_admin: true });
	fireEvent.click(screen.getByRole("button", { name: "Viewer" }));
	expect(screen.getByRole("menuitem", { name: "Settings" })).toBeTruthy();
});

test("Escape dismisses the menu and restores focus to its trigger", () => {
	stubFetch();
	renderNavbar();
	const trigger = screen.getByRole("button", { name: "Viewer" });
	fireEvent.click(trigger);
	expect(trigger.getAttribute("aria-expanded")).toBe("true");
	fireEvent.keyDown(document, { key: "Escape" });
	expect(screen.queryByRole("menu")).toBeNull();
	expect(trigger.getAttribute("aria-expanded")).toBe("false");
	expect(document.activeElement).toBe(trigger);
});

test("outside activation dismisses the user menu", () => {
	stubFetch();
	renderNavbar();
	fireEvent.click(screen.getByRole("button", { name: "Viewer" }));
	fireEvent.pointerDown(document.body);
	expect(screen.queryByRole("menu")).toBeNull();
});

test("confirmed reset calls the endpoint and refetches home", async () => {
	const fetchMock = stubFetch();
	vi.stubGlobal(
		"confirm",
		vi.fn(() => true),
	);
	const queryClient = renderNavbar();

	openMenuAndReset();

	await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
	const [url, init] = fetchMock.mock.calls[0];
	expect(String(url)).toBe("/api/v1/recommendations/reset");
	expect(init?.method).toBe("POST");
	await waitFor(() =>
		expect(queryClient.getQueryState(["home"])?.isInvalidated).toBe(true),
	);
});
