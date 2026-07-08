import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { Availability } from "../lib/api";
import { RequestButton } from "./RequestButton";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

function av(status: Availability["status"], known = true): Availability {
	return { status, known };
}

/** Route fetches by URL substring; unmatched paths 404. Returns the mock. */
function stubFetch(routes: Record<string, unknown>) {
	const mock = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		for (const [path, body] of Object.entries(routes)) {
			if (url.includes(path)) {
				return { ok: true, status: 200, json: async () => body } as Response;
			}
		}
		return {
			ok: false,
			status: 404,
			json: async () => ({ detail: "x" }),
		} as Response;
	});
	vi.stubGlobal("fetch", mock);
	return mock;
}

function renderButton(availability?: Availability | null) {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={queryClient}>
			<RequestButton type="movie" id={42} availability={availability} />
		</QueryClientProvider>,
	);
}

const SEERR_ON = { tmdb_configured: true, seerr_configured: true };
const SEERR_OFF = { tmdb_configured: true, seerr_configured: false };

test("submits a request through the client and confirms success", async () => {
	stubFetch({
		"/api/v1/config": SEERR_ON,
		"/api/v1/request": {
			status: "ok",
			availability: av("pending"),
			seerr_url: "https://requests.example/movie/42",
		},
	});
	renderButton(av("not_requested"));

	fireEvent.click(await screen.findByRole("button", { name: "Request" }));

	expect(await screen.findByText("Requested ✓")).toBeTruthy();
});

test("prompts re-login when the backend signals re_auth_required", async () => {
	stubFetch({
		"/api/v1/config": SEERR_ON,
		"/api/v1/request": {
			status: "re_auth_required",
			availability: null,
			seerr_url: null,
		},
	});
	renderButton(av("not_requested"));

	fireEvent.click(await screen.findByRole("button", { name: "Request" }));

	const alert = await screen.findByRole("alert");
	expect(alert.textContent).toContain("sign in again");
});

test("offers the server-built Seerr fallback link on failure", async () => {
	stubFetch({
		"/api/v1/config": SEERR_ON,
		"/api/v1/request": {
			status: "failed",
			availability: null,
			seerr_url: "https://requests.example/movie/42",
		},
	});
	renderButton(av("not_requested"));

	fireEvent.click(await screen.findByRole("button", { name: "Request" }));

	const link = await screen.findByRole("link", { name: /Request in Seerr/ });
	expect(link.getAttribute("href")).toBe("https://requests.example/movie/42");
});

test("renders no affordance when Seerr is unconfigured", async () => {
	const mock = stubFetch({ "/api/v1/config": SEERR_OFF });
	renderButton(av("not_requested"));

	await waitFor(() => expect(mock).toHaveBeenCalled()); // config resolved
	expect(screen.queryByRole("button")).toBeNull();
});

test("shows no request button when the title is already available", async () => {
	stubFetch({ "/api/v1/request": {}, "/api/v1/config": SEERR_ON });
	renderButton(av("available"));

	await waitFor(() =>
		expect(screen.queryByRole("button", { name: "Request" })).toBeNull(),
	);
});
