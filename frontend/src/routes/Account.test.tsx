import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
	within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { AccountResponse, TasteSource } from "../lib/api";
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
	taste_sources: { plex: true, seerr: true, jellyfin: true, browsing: true },
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
function setup(
	summary: Pick<AccountResponse, "providers"> &
		Partial<Pick<AccountResponse, "taste_sources">> = SUMMARY,
	error = false,
) {
	const fetch = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
		const url = String(input);
		const status = url.endsWith("/account") ? 200 : error ? 409 : 204;
		return {
			ok: status < 400,
			status,
			json: async () =>
				status === 200
					? { ...SUMMARY, ...summary }
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

const sources: TasteSource[] = ["plex", "seerr", "jellyfin", "browsing"];
const sourceLabels = {
	plex: "Plex history",
	seerr: "Seerr request history",
	jellyfin: "Jellyfin history",
	browsing: "Browsing activity",
};
const clearNames = {
	plex: "Clear imported history from Plex",
	seerr: "Clear imported history from Seerr",
	jellyfin: "Clear imported history from Jellyfin",
	browsing: "Clear browsing activity",
};

test.each([
	"plex",
	"seerr",
	"jellyfin",
] as const)("%s controls stay on configured, dormant, and retained-history cards", async (provider) => {
	for (const [available, linked] of [
		[true, true],
		[true, false],
		[false, true],
		[false, false],
	]) {
		const view = setup({
			providers: [{ provider, available, linked, can_unlink: true }],
		});
		const toggle = await screen.findByRole("switch", {
			name: `Use ${sourceLabels[provider]} for recommendations`,
		});
		const card = within(toggle.closest("section") as HTMLElement);
		const clearButton = card.getByRole("button", {
			name: clearNames[provider],
		});
		expect(clearButton.getAttribute("aria-label")).toContain(
			clearButton.textContent?.trim(),
		);
		if (!available && !linked) {
			expect(card.queryByText("Not connected")).toBeNull();
			expect(card.queryByText("No longer available on this server")).toBeNull();
			expect(card.queryByRole("button", { name: /Link|Unlink/ })).toBeNull();
		}
		view.cache.clear();
		cleanup();
	}
});

test.each(
	sources,
)("%s clears only after confirmation and supports cancel", async (source) => {
	const { fetch } = setup({
		providers: [
			...SUMMARY.providers,
			{
				provider: "jellyfin",
				available: true,
				linked: false,
				can_unlink: false,
			},
		],
	});
	fireEvent.click(
		await screen.findByRole("button", {
			name: clearNames[source],
		}),
	);
	const path = `/api/v1/account/taste-sources/${source}/clear`;
	expect(fetch.mock.calls.some(([url]) => String(url) === path)).toBe(false);
	fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
	expect(screen.queryByRole("dialog")).toBeNull();
	expect(fetch.mock.calls.some(([url]) => String(url) === path)).toBe(false);
	fireEvent.click(screen.getByRole("button", { name: clearNames[source] }));
	fireEvent.click(screen.getByRole("button", { name: "Confirm clear" }));
	await waitFor(() =>
		expect(fetch).toHaveBeenCalledWith(
			path,
			expect.objectContaining({ method: "POST" }),
		),
	);
	await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

test("clearing a retained-history card restores focus when the card disappears", async () => {
	const { fetch } = setup({
		providers: [
			{ provider: "plex", available: false, linked: false, can_unlink: false },
		],
	});
	const trigger = await screen.findByRole("button", { name: clearNames.plex });
	trigger.focus();
	fireEvent.click(trigger);
	fetch.mockImplementation(async (input) =>
		String(input).endsWith("/account")
			? ({
					ok: true,
					status: 200,
					json: async () => ({ ...SUMMARY, providers: [] }),
				} as Response)
			: ({ ok: true, status: 204 } as Response),
	);
	fireEvent.click(screen.getByRole("button", { name: "Confirm clear" }));
	await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
	await waitFor(() =>
		expect(screen.queryByRole("button", { name: clearNames.plex })).toBeNull(),
	);
	await waitFor(() =>
		expect(document.activeElement).toBe(
			screen.getByRole("heading", { name: "Connected accounts" }),
		),
	);
});

test("failed toggle is optimistic, rolls back, and shows only a generic error", async () => {
	const { fetch, cache } = setup();
	const toggle = await screen.findByRole("switch", {
		name: "Use Plex history for recommendations",
	});
	let finish: ((response: Response) => void) | undefined;
	const pending = new Promise<Response>((resolve) => {
		finish = resolve;
	});
	fetch.mockImplementation(async (input) =>
		String(input).endsWith("/taste-sources")
			? pending
			: ({ ok: true, status: 200, json: async () => SUMMARY } as Response),
	);
	fireEvent.click(toggle);
	await waitFor(() => expect(toggle).toHaveProperty("checked", false));
	expect(
		cache.getQueryData<AccountResponse>(["account"])?.taste_sources.plex,
	).toBe(false);
	finish?.({
		ok: false,
		status: 500,
		json: async () => ({ detail: "private failure detail" }),
	} as Response);
	expect(await screen.findByRole("alert")).toHaveProperty(
		"textContent",
		"Could not update taste source. Try again.",
	);
	expect(toggle).toHaveProperty("checked", true);
	expect(screen.queryByText("private failure detail")).toBeNull();
});

test.each(
	sources,
)("%s toggle follows server state and refreshes taste queries", async (source) => {
	const summary = {
		...SUMMARY,
		providers: [
			...SUMMARY.providers,
			{
				provider: "jellyfin" as const,
				available: true,
				linked: false,
				can_unlink: false,
			},
		],
		taste_sources: { ...SUMMARY.taste_sources, [source]: false },
	};
	const { fetch, cache } = setup(summary);
	const toggle = await screen.findByRole("switch", {
		name: `Use ${sourceLabels[source]} for recommendations`,
	});
	expect(toggle).toHaveProperty("checked", false);
	for (const key of [
		"home",
		"rails",
		"explain",
		"household-members",
		"taste-onboarding",
	])
		cache.setQueryData([key], {});
	fetch.mockImplementation(async (input, init) => {
		if (String(input).endsWith("/taste-sources")) {
			summary.taste_sources = { ...summary.taste_sources, [source]: true };
			expect(init?.body).toBe(JSON.stringify({ source, enabled: true }));
			return { ok: true, status: 204 } as Response;
		}
		return { ok: true, status: 200, json: async () => summary } as Response;
	});
	fireEvent.click(toggle);
	await waitFor(() => expect(toggle).toHaveProperty("checked", true));
	await waitFor(() =>
		expect(cache.getQueryState(["home"])?.isInvalidated).toBe(true),
	);
	for (const key of [
		"rails",
		"explain",
		"household-members",
		"taste-onboarding",
	])
		expect(cache.getQueryState([key])?.isInvalidated).toBe(true);
});

test("late toggle failure cannot restore another member's account state", async () => {
	const { fetch, cache } = setup();
	const toggle = await screen.findByRole("switch", {
		name: "Use Plex history for recommendations",
	});
	let finish: ((response: Response) => void) | undefined;
	const pending = new Promise<Response>((resolve) => {
		finish = resolve;
	});
	let currentAccount = SUMMARY;
	fetch.mockImplementation(async (input) =>
		String(input).endsWith("/taste-sources")
			? pending
			: ({
					ok: true,
					status: 200,
					json: async () => currentAccount,
				} as Response),
	);
	fireEvent.click(toggle);
	await waitFor(() => expect(toggle).toHaveProperty("checked", false));
	const nextAccount = { ...SUMMARY, providers: [] };
	currentAccount = nextAccount;
	await setConfirmedSession(cache, { ...USER, id: 2 });
	cache.setQueryData(["account"], nextAccount);
	finish?.({
		ok: false,
		status: 500,
		json: async () => ({ detail: "failed" }),
	} as Response);
	await pending;
	await screen.findByRole("alert");
	expect(cache.getQueryData(["account"])).toEqual(nextAccount);
});

test("Jellyfin card links with credentials and offers the history choice on unlink", async () => {
	const { fetch } = setup({
		providers: [
			{
				provider: "jellyfin",
				available: true,
				linked: false,
				can_unlink: false,
			},
		],
	});
	fireEvent.click(await screen.findByRole("button", { name: "Link Jellyfin" }));
	fireEvent.change(screen.getByLabelText("Username"), {
		target: { value: "viewer" },
	});
	fireEvent.change(screen.getByLabelText("Password"), {
		target: { value: "pw" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Connect Jellyfin" }));
	await waitFor(() =>
		expect(fetch).toHaveBeenCalledWith(
			"/api/v1/account/links/jellyfin",
			expect.objectContaining({
				body: JSON.stringify({ username: "viewer", password: "pw" }),
			}),
		),
	);
});

test.each([
	true,
	false,
])("Seerr dialog offers Jellyfin only while available: %s", async (available) => {
	const { fetch } = setup({
		providers: [
			{ provider: "seerr", available: true, linked: false, can_unlink: false },
			{ provider: "jellyfin", available, linked: false, can_unlink: false },
		],
	});
	fireEvent.click(await screen.findByRole("button", { name: "Link Seerr" }));
	if (!available) {
		expect(
			screen.queryByRole("button", { name: "Use Jellyfin credentials" }),
		).toBeNull();
		return;
	}
	fireEvent.click(
		await screen.findByRole("button", { name: "Use Jellyfin credentials" }),
	);
	fireEvent.change(screen.getByLabelText("Username"), {
		target: { value: "viewer" },
	});
	fireEvent.change(screen.getByLabelText("Password"), {
		target: { value: "pw" },
	});
	fireEvent.click(screen.getByRole("button", { name: "Connect Seerr" }));
	await waitFor(() =>
		expect(fetch).toHaveBeenCalledWith(
			"/api/v1/account/links/seerr",
			expect.objectContaining({
				body: JSON.stringify({
					method: "jellyfin",
					username: "viewer",
					password: "pw",
				}),
			}),
		),
	);
});

test("dormant Jellyfin card remains unlinkable and deletion names all upstreams", async () => {
	setup({
		providers: [
			{
				provider: "jellyfin",
				available: false,
				linked: true,
				display_name: "Jellyfin member",
				can_unlink: true,
			},
		],
	});
	expect(await screen.findByText("Jellyfin member")).toBeTruthy();
	fireEvent.click(screen.getByRole("button", { name: "Unlink Jellyfin" }));
	expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(
		false,
	);
	fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
	fireEvent.click(
		screen.getByRole("button", { name: "Delete my Tasterr account" }),
	);
	expect(screen.getByText(/Plex, Jellyfin, or Seerr/)).toBeTruthy();
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
	expect(
		screen.getByText(/Nothing is deleted in Plex, Jellyfin, or Seerr/),
	).toBeTruthy();
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
