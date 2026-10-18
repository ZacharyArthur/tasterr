import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { AccountResponse } from "../lib/api";
import { setConfirmedSession } from "../lib/auth";
import { Account } from "./Account";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});
const USER = {
	id: 1,
	display_name: "House Member",
	avatar_url: null,
	is_admin: false,
};
const SUMMARY: AccountResponse = {
	providers: [
		{
			provider: "plex",
			linked: true,
			available: true,
			display_name: "Plex member",
			linked_at: "2026-01-01",
			can_unlink: true,
		},
		{
			provider: "seerr",
			linked: true,
			available: true,
			display_name: "Seerr member",
			linked_at: "2026-01-01",
			can_unlink: true,
		},
	],
};
function setup(summary = SUMMARY, error = false) {
	const fetch = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		const status = url.endsWith("/account") ? 200 : error ? 409 : 204;
		return {
			ok: status < 400,
			status,
			json: async () =>
				status === 200
					? summary
					: {
							detail:
								"Sign in with each account, keep one, delete the other Tasterr account, then link again.",
						},
		} as Response;
	});
	vi.stubGlobal("fetch", fetch);
	const cache = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={cache}>
			<Account user={USER} />
		</QueryClientProvider>,
	);
	return { fetch, cache };
}
test("member sees providers, name, and deletion controls", async () => {
	setup();
	expect(await screen.findByText("Plex member")).toBeTruthy();
	expect(screen.getByText("Seerr member")).toBeTruthy();
	expect(
		screen.getByRole("button", { name: "Delete my Tasterr account" }),
	).toBeTruthy();
});
test("unlink starts with history unticked and forwards the choice", async () => {
	const { fetch } = setup();
	fireEvent.click(await screen.findByRole("button", { name: "Unlink Plex" }));
	const checkbox = screen.getByRole("checkbox") as HTMLInputElement;
	expect(checkbox.checked).toBe(false);
	fireEvent.click(checkbox);
	fireEvent.click(screen.getByRole("button", { name: "Confirm unlink" }));
	await waitFor(() =>
		expect(fetch).toHaveBeenCalledWith(
			"/api/v1/account/links/plex/unlink",
			expect.objectContaining({
				body: JSON.stringify({ delete_history: true }),
			}),
		),
	);
});
test("only remaining sign-in is disabled and dormant account remains unlinkable", async () => {
	setup({
		providers: [
			{ ...SUMMARY.providers[0], available: false },
			{ ...SUMMARY.providers[1], can_unlink: false },
		],
	});
	expect(
		await screen.findByText("No longer available on this server"),
	).toBeTruthy();
	expect(
		(screen.getByRole("button", { name: "Unlink Seerr" }) as HTMLButtonElement)
			.disabled,
	).toBe(true);
	expect(
		(screen.getByRole("button", { name: "Unlink Plex" }) as HTMLButtonElement)
			.disabled,
	).toBe(false);
	expect(screen.getByText("This is your only way to sign in")).toBeTruthy();
});
test("Seerr connection shows conflict guidance and supports Escape", async () => {
	setup(
		{
			providers: [
				SUMMARY.providers[0],
				{
					provider: "seerr",
					linked: false,
					available: true,
					can_unlink: false,
				},
			],
		},
		true,
	);
	fireEvent.click(await screen.findByRole("button", { name: "Link Seerr" }));
	fireEvent.click(
		await screen.findByRole("button", { name: "Use my Plex account" }),
	);
	expect(await screen.findByRole("alert")).toHaveProperty(
		"textContent",
		expect.stringContaining("delete the other"),
	);
	fireEvent.keyDown(document, { key: "Escape" });
	expect(screen.queryByRole("dialog")).toBeNull();
});
test("deletion requires the name, sends it, and clears the session", async () => {
	const { fetch, cache } = setup();
	fireEvent.click(
		screen.getByRole("button", { name: "Delete my Tasterr account" }),
	);
	const button = screen.getByRole("button", {
		name: "Permanently delete account",
	}) as HTMLButtonElement;
	expect(button.disabled).toBe(true);
	expect(screen.getByText(/Nothing is deleted in Plex or Seerr/)).toBeTruthy();
	fireEvent.change(screen.getByLabelText("Type House Member to confirm"), {
		target: { value: USER.display_name },
	});
	fireEvent.click(button);
	await waitFor(() => expect(cache.getQueryData(["auth", "me"])).toBeNull());
	expect(fetch).toHaveBeenCalledWith(
		"/api/v1/account/delete",
		expect.objectContaining({
			body: JSON.stringify({ confirm: USER.display_name }),
		}),
	);
});

test("a late deletion response preserves a newer confirmed session", async () => {
	const { fetch, cache } = setup();
	let finish: ((response: Response) => void) | undefined;
	const pending = new Promise<Response>((resolve) => {
		finish = resolve;
	});
	fetch.mockImplementation(async (input) =>
		String(input).endsWith("/delete")
			? pending
			: ({ ok: true, status: 200, json: async () => SUMMARY } as Response),
	);
	fireEvent.click(
		screen.getByRole("button", { name: "Delete my Tasterr account" }),
	);
	fireEvent.change(screen.getByLabelText("Type House Member to confirm"), {
		target: { value: USER.display_name },
	});
	fireEvent.click(
		screen.getByRole("button", { name: "Permanently delete account" }),
	);
	await waitFor(() =>
		expect(fetch).toHaveBeenCalledWith(
			"/api/v1/account/delete",
			expect.anything(),
		),
	);
	const nextUser = { ...USER, id: 2 };
	await setConfirmedSession(cache, nextUser);
	finish?.({ ok: true, status: 204 } as Response);
	await pending;
	await waitFor(() =>
		expect(cache.getQueryData(["auth", "me"])).toEqual(nextUser),
	);
});
