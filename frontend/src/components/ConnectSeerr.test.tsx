import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	act,
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { AccountResponse } from "../lib/api";
import { ConnectSeerr } from "./ConnectSeerr";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

test.each([
	{
		name: "Plex-backed with local on",
		accepts: { plex: true, jellyfin: false, local: true },
		plex: true,
		jellyfin: true,
		form: "Email",
		action: true,
		guidance: [],
		toggle: false,
	},
	{
		name: "local off without Plex link",
		accepts: { plex: true, jellyfin: false, local: false },
		plex: false,
		jellyfin: true,
		form: null,
		action: false,
		guidance: ["Link Plex on your Account page to enable requests."],
		toggle: false,
	},
	{
		name: "local refused opens Jellyfin",
		accepts: { plex: false, jellyfin: true, local: false },
		plex: false,
		jellyfin: true,
		form: "Username",
		action: false,
		guidance: [],
		toggle: false,
	},
	{
		name: "all methods refused",
		accepts: { plex: false, jellyfin: false, local: false },
		plex: false,
		jellyfin: true,
		form: null,
		action: false,
		guidance: ["Requests are unavailable for this account."],
		toggle: false,
	},
	{
		name: "Plex action alone",
		accepts: { plex: true, jellyfin: false, local: false },
		plex: true,
		jellyfin: true,
		form: null,
		action: true,
		guidance: [],
		toggle: false,
	},
	{
		name: "Jellyfin-only member with Plex-backed Seerr",
		accepts: { plex: true, jellyfin: false, local: true },
		plex: false,
		jellyfin: true,
		form: "Email",
		action: false,
		guidance: [
			"Link Plex on your Account page to enable requests.",
			"Ask your household admin for a Seerr local account.",
		],
		toggle: false,
	},
	{
		name: "accepted Jellyfin unconfigured",
		accepts: { plex: false, jellyfin: true, local: false },
		plex: false,
		jellyfin: false,
		form: null,
		action: false,
		guidance: ["Requests are unavailable for this account."],
		toggle: false,
	},
	{
		name: "all accepted preserves layout",
		accepts: { plex: true, jellyfin: true, local: true },
		plex: true,
		jellyfin: true,
		form: "Email",
		action: true,
		guidance: [],
		toggle: true,
	},
])("$name", async ({
	accepts,
	plex,
	jellyfin,
	form,
	action,
	guidance,
	toggle,
}) => {
	const account: AccountResponse = {
		seerr_accepts: accepts,
		taste_sources: { plex: true, jellyfin: true, seerr: true, browsing: true },
		providers: [
			{
				provider: "plex",
				available: true,
				sign_in: true,
				linked: plex,
				can_unlink: false,
			},
			{
				provider: "jellyfin",
				available: jellyfin,
				sign_in: jellyfin,
				linked: jellyfin,
				can_unlink: false,
			},
		],
	};
	const cache = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	cache.setQueryData(["account"], account);
	vi.stubGlobal(
		"fetch",
		vi.fn(async () => ({ ok: true, status: 200, json: async () => account })),
	);
	render(
		<QueryClientProvider client={cache}>
			<ConnectSeerr onConnected={vi.fn()} onCancel={vi.fn()} />
		</QueryClientProvider>,
	);
	expect(
		await screen.findByRole("dialog", { name: "Connect Seerr" }),
	).toBeTruthy();
	expect(!!screen.queryByRole("button", { name: "Use my Plex account" })).toBe(
		action,
	);
	expect(
		!!screen.queryByRole("button", { name: "Use Jellyfin credentials" }),
	).toBe(toggle);
	expect(!!screen.queryByLabelText("Email")).toBe(form === "Email");
	expect(!!screen.queryByLabelText("Username")).toBe(form === "Username");
	expect(!!screen.queryByLabelText("Password")).toBe(form !== null);
	const guidanceText =
		screen
			.queryByText(
				/Link Plex on your Account page|Ask your household admin|Requests are unavailable/,
			)
			?.textContent?.trim() ?? "";
	expect(guidanceText).toBe(guidance.join(" "));
	if (form) {
		expect(
			screen.getByText(
				form === "Email"
					? "Sign in with your Seerr account email and password."
					: "Sign in with your Jellyfin username and password.",
			),
		).toBeTruthy();
	} else {
		expect(screen.queryByText(/Sign in with your/)).toBeNull();
	}
	if (toggle) {
		fireEvent.click(
			screen.getByRole("button", { name: "Use Jellyfin credentials" }),
		);
		expect(screen.getByLabelText("Username")).toBeTruthy();
		fireEvent.click(
			screen.getByRole("button", { name: "Use Seerr email instead" }),
		);
		expect(screen.getByLabelText("Email")).toBeTruthy();
	}
});

test.each([
	false,
	true,
])("cold account lookup keeps focus in the dialog: Jellyfin offered %s", async (jellyfin) => {
	let respond!: (response: Response) => void;
	const pending = new Promise<Response>((resolve) => {
		respond = resolve;
	});
	vi.stubGlobal(
		"fetch",
		vi.fn(() => pending),
	);
	const cache = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={cache}>
			<ConnectSeerr onConnected={vi.fn()} onCancel={vi.fn()} />
		</QueryClientProvider>,
	);
	const dialog = screen.getByRole("dialog", { name: "Connect Seerr" });
	expect(document.activeElement).toBe(screen.getByLabelText("Email"));
	await act(async () => {
		respond({
			ok: true,
			status: 200,
			json: async () => ({
				seerr_accepts: { plex: false, jellyfin, local: false },
				providers: [
					{
						provider: "jellyfin",
						available: jellyfin,
						linked: jellyfin,
						sign_in: jellyfin,
						can_unlink: false,
					},
				],
				taste_sources: {
					plex: true,
					jellyfin: true,
					seerr: true,
					browsing: true,
				},
			}),
		} as Response);
	});
	await waitFor(() => {
		expect(screen.queryByLabelText("Email")).toBeNull();
		expect(dialog.contains(document.activeElement)).toBe(true);
	});
	if (jellyfin) expect(screen.getByLabelText("Username")).toBeTruthy();
	else
		expect(document.activeElement).toBe(
			screen.getByRole("button", { name: "Cancel" }),
		);
});
