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
import { Settings } from "./Settings";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

const SETTINGS = {
	settings: {
		region: "US",
		service_ids: [8],
		disabled_rail_types: [],
		appearance: { theme: "dark", accent: "crimson" },
	},
	rail_types: [
		{ id: "popular", label: "Popular" },
		{ id: "genres", label: "Genres" },
	],
};
const REGIONS = {
	regions: [
		{ code: "US", name: "United States" },
		{ code: "GB", name: "United Kingdom" },
	],
};
const SERVICES = {
	region: "US",
	services: [
		{ provider_id: 8, name: "Netflix", logo_path: null, display_priority: 1 },
		{
			provider_id: 9,
			name: "Prime Video",
			logo_path: null,
			display_priority: 2,
		},
	],
};

function response(body: unknown, status = 200): Response {
	return { ok: status < 400, status, json: async () => body } as Response;
}

function renderSettings(fetchMock: ReturnType<typeof vi.fn>) {
	vi.stubGlobal("fetch", fetchMock);
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={queryClient}>
			<MemoryRouter>
				<Settings />
			</MemoryRouter>
		</QueryClientProvider>,
	);
	return queryClient;
}

function routeAdminFetch() {
	return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
		const url = String(input);
		if (url === "/api/v1/settings" && init?.method === "PUT") {
			return response({ ...SETTINGS, settings: JSON.parse(String(init.body)) });
		}
		if (url === "/api/v1/settings") return response(SETTINGS);
		if (url === "/api/v1/regions") return response(REGIONS);
		if (url.includes("/api/v1/services"))
			return response({
				...SERVICES,
				region: url.endsWith("GB") ? "GB" : "US",
			});
		if (url === "/api/v1/connection-test")
			return response({
				target: "tmdb",
				ok: true,
				detail: "Connection successful",
			});
		return response({});
	});
}

test("initializes the complete draft and saves only the typed runtime document", async () => {
	const fetchMock = routeAdminFetch();
	const queryClient = renderSettings(fetchMock);
	expect(await screen.findByRole("heading", { name: "Settings" })).toBeTruthy();
	expect((screen.getByLabelText("Region") as HTMLSelectElement).value).toBe(
		"US",
	);
	expect(
		((await screen.findByLabelText("Netflix")) as HTMLInputElement).checked,
	).toBe(true);

	fireEvent.click(screen.getByLabelText("Prime Video"));
	fireEvent.click(screen.getByLabelText("Popular"));
	fireEvent.click(screen.getByLabelText("light"));
	fireEvent.click(screen.getByLabelText("Azure"));
	fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

	expect(await screen.findByText("Settings saved.")).toBeTruthy();
	const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
	expect(JSON.parse(String(put?.[1]?.body))).toEqual({
		region: "US",
		service_ids: [8, 9],
		disabled_rail_types: ["popular"],
		appearance: { theme: "light", accent: "azure" },
	});
	for (const key of [["config"], ["home"], ["rails"], ["title"]]) {
		expect(queryClient.getQueryState(key)?.isInvalidated ?? true).toBe(true);
	}
	expect(screen.queryByLabelText(/key|token|url|secret/i)).toBeNull();
});

test("changing region clears selections and loads region services", async () => {
	const fetchMock = routeAdminFetch();
	renderSettings(fetchMock);
	await screen.findByLabelText("Netflix");
	fireEvent.change(screen.getByLabelText("Region"), {
		target: { value: "GB" },
	});
	await waitFor(() =>
		expect(fetchMock).toHaveBeenCalledWith(
			"/api/v1/services?region=GB",
			undefined,
		),
	);
	expect(screen.queryByText(/Selected:/)).toBeNull();
});

test("connection results are announced without exposing configuration", async () => {
	const fetchMock = routeAdminFetch();
	renderSettings(fetchMock);
	await screen.findByRole("heading", { name: "Settings" });
	await screen.findByLabelText("Netflix");
	fireEvent.click(screen.getByRole("button", { name: "Test TMDB" }));
	const result = await screen.findByText("TMDB: Connection successful");
	expect(result.tagName).toBe("OUTPUT");
	const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
	expect(JSON.parse(String(post?.[1]?.body))).toEqual({ target: "tmdb" });
});
