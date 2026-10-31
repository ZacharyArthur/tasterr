import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	act,
	cleanup,
	fireEvent,
	render,
	screen,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { TraktConnect } from "./TraktConnect";

afterEach(() => {
	cleanup();
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

function setup(
	outcomes: Array<{ status?: string; http?: number; interval?: number }> = [
		{ status: "pending" },
	],
	startError = false,
	expires = 12,
	create?: () => Promise<Response>,
) {
	vi.useFakeTimers();
	let polls = 0;
	const fetch = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
		const polling = String(input).endsWith("/poll");
		if (!polling && create) return create();
		const result = polling
			? outcomes[Math.min(polls++, outcomes.length - 1)]
			: undefined;
		const status = result?.http ?? (startError && !polling ? 502 : 200);
		return {
			ok: status < 400,
			status,
			json: async () =>
				polling
					? status >= 400
						? { detail: "Connection conflict" }
						: { status: result?.status, interval: result?.interval ?? 2 }
					: {
							handle: "opaque",
							user_code: "ABCD1234",
							interval: 2,
							expires_in: expires,
							verification_url: "https://untrusted.invalid",
						},
		} as Response;
	});
	vi.stubGlobal("fetch", fetch);
	const linked = vi.fn();
	const cache = new QueryClient({
		defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
	});
	render(
		<QueryClientProvider client={cache}>
			<TraktConnect onLinked={linked} />
		</QueryClientProvider>,
	);
	fireEvent.click(screen.getByRole("button", { name: "Link Trakt" }));
	return { fetch, linked };
}

async function tick(ms = 0) {
	await act(async () => {
		await vi.advanceTimersByTimeAsync(ms);
	});
}

test.each([200, 502])("ignores stale creation %s", async (status) => {
	const completions: Array<(response: Response) => void> = [];
	const { fetch } = setup(
		[{ status: "pending" }],
		false,
		60,
		() => new Promise<Response>((resolve) => completions.push(resolve)),
	);
	await tick();
	fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
	fireEvent.click(screen.getByRole("button", { name: "Link Trakt" }));
	await tick();
	expect(completions).toHaveLength(2);
	const response = (code: string, http = 200) =>
		new Response(
			JSON.stringify({
				handle: code,
				user_code: code,
				interval: 2,
				expires_in: 60,
			}),
			{ status: http },
		);
	completions[1](response("NEWCODE"));
	await tick();
	expect(screen.getByText("NEWCODE")).toBeTruthy();
	completions[0](response("OLDCODE", status));
	await tick();
	expect(screen.getByText("NEWCODE")).toBeTruthy();
	expect(screen.queryByText("OLDCODE")).toBeNull();
	expect(screen.queryByRole("alert")).toBeNull();
	await tick(2000);
	const polls = fetch.mock.calls.filter(([input]) =>
		String(input).endsWith("/poll"),
	);
	expect(polls).toHaveLength(1);
	expect(JSON.parse(String(polls[0][1]?.body))).toEqual({ handle: "NEWCODE" });
});

test("slow-down interval survives a transient polling error", async () => {
	const { fetch, linked } = setup(
		[{ status: "pending", interval: 7 }, { http: 502 }, { status: "linked" }],
		false,
		60,
	);
	await tick();
	await tick(2000);
	await tick(7000);
	const calls = fetch.mock.calls.length;
	await tick(2000);
	expect(fetch.mock.calls).toHaveLength(calls);
	await tick(5000);
	expect(linked).toHaveBeenCalledOnce();
});

test("shows code, fixed secure activation link, pending and cancel", async () => {
	const { fetch } = setup();
	await tick();
	expect(screen.getByText("ABCD1234")).toBeTruthy();
	const link = screen.getByRole("link", { name: "Open Trakt activation" });
	expect(link.getAttribute("href")).toBe("https://auth.trakt.tv/activate");
	expect(link.getAttribute("target")).toBe("_blank");
	expect(link.getAttribute("rel")).toBe("noopener noreferrer");
	expect(document.body.innerHTML).not.toContain("untrusted.invalid");
	await tick(2000);
	expect(screen.getByRole("status").textContent).toContain("Waiting");
	fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
	const calls = fetch.mock.calls.length;
	await tick(20000);
	expect(fetch.mock.calls).toHaveLength(calls);
	expect(screen.queryByRole("dialog")).toBeNull();
});

test.each(["expired", "denied"])("%s offers start again", async (status) => {
	setup([{ status }]);
	await tick();
	await tick(2000);
	expect(screen.getByRole("button", { name: "Start again" })).toBeTruthy();
	if (status === "denied")
		expect(screen.getByRole("alert").textContent).toContain(
			"community-app limit",
		);
	await tick(15000);
	if (status === "denied")
		expect(screen.getByRole("alert").textContent).toContain(
			"community-app limit",
		);
});

test.each([
	404, 409,
])("failed or consumed handle %s offers start again", async (http) => {
	setup([{ http }]);
	await tick();
	await tick(2000);
	expect(screen.getByRole("button", { name: "Start again" })).toBeTruthy();
});

test("transient error keeps polling and can link", async () => {
	const { linked } = setup([{ http: 502 }, { status: "linked" }]);
	await tick();
	await tick(2000);
	expect(screen.getByRole("alert").textContent).toContain("Still waiting");
	await tick(2000);
	expect(linked).toHaveBeenCalledOnce();
	expect(screen.queryByRole("dialog")).toBeNull();
});

test("expiry and failed creation both offer restart", async () => {
	setup();
	await tick();
	await tick(12000);
	expect(screen.getByRole("alert").textContent).toContain("expired");
	cleanup();
	setup([], true);
	await tick();
	expect(screen.getByRole("alert").textContent).toContain("Could not start");
	expect(screen.getByRole("button", { name: "Start again" })).toBeTruthy();
});
