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
import { setConfirmedSession } from "../lib/auth";
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
		hide_library_items: false,
		excluded_service_ids: [],
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

function renderSettings(
	fetchMock: ReturnType<typeof vi.fn>,
	queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	}),
) {
	vi.stubGlobal("fetch", fetchMock);
	render(
		<QueryClientProvider client={queryClient}>
			<MemoryRouter>
				<Settings />
			</MemoryRouter>
		</QueryClientProvider>,
	);
	return queryClient;
}

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((done) => {
		resolve = done;
	});
	return { promise, resolve };
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
		hide_library_items: false,
		excluded_service_ids: [],
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

test("saves exclusions separately from selected services and clears them on region change", async () => {
	const fetchMock = routeAdminFetch();
	renderSettings(fetchMock);
	await screen.findByLabelText("Exclude Netflix");
	fireEvent.click(screen.getByLabelText("Hide titles already in the library"));
	fireEvent.click(screen.getByLabelText("Exclude Netflix"));
	expect((screen.getByLabelText("Netflix") as HTMLInputElement).checked).toBe(
		true,
	);
	fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
	await screen.findByText("Settings saved.");
	const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
	expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({
		service_ids: [8],
		hide_library_items: true,
		excluded_service_ids: [8],
	});
	fireEvent.change(screen.getByLabelText("Region"), {
		target: { value: "GB" },
	});
	await waitFor(() =>
		expect(
			(screen.getByLabelText("Exclude Netflix") as HTMLInputElement).checked,
		).toBe(false),
	);
});

test("shows environment locks and preserves locked exclusions when changing region", async () => {
	const excludedIds = [8, 99, 100, 101, 102, 103, 104, 105];
	const baseFetch = routeAdminFetch();
	const fetchMock = vi.fn(
		async (input: RequestInfo | URL, init?: RequestInit) => {
			if (String(input) === "/api/v1/settings" && !init?.method)
				return response({
					...SETTINGS,
					settings: {
						...SETTINGS.settings,
						hide_library_items: true,
						excluded_service_ids: excludedIds,
					},
					locked_fields: ["hide_library_items", "excluded_service_ids"],
				});
			return baseFetch(input, init);
		},
	);
	renderSettings(fetchMock);
	await screen.findByLabelText("Exclude Netflix");
	expect(screen.queryByText(/Exclusion limit reached/)).toBeNull();
	expect(
		(
			screen.getByLabelText(
				"Hide titles already in the library",
			) as HTMLInputElement
		).disabled,
	).toBe(true);
	expect(
		(
			screen
				.getByLabelText("Exclude Netflix")
				.closest("fieldset") as HTMLFieldSetElement
		).disabled,
	).toBe(true);
	expect(
		screen.getByText(
			"Service exclusions are controlled by an environment variable.",
		),
	).toBeTruthy();
	fireEvent.change(screen.getByLabelText("Region"), {
		target: { value: "GB" },
	});
	await screen.findByLabelText("Exclude Netflix");
	expect(
		(screen.getByLabelText("Exclude Netflix") as HTMLInputElement).checked,
	).toBe(true);
	fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
	await screen.findByText("Settings saved.");
	const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
	expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({
		region: "GB",
		excluded_service_ids: excludedIds,
	});
});

test("missing excluded services stay removable at the eight-service limit", async () => {
	const missingIds = Array.from({ length: 8 }, (_, index) => 99 + index);
	const baseFetch = routeAdminFetch();
	const fetchMock = vi.fn(
		async (input: RequestInfo | URL, init?: RequestInit) => {
			if (String(input) === "/api/v1/settings" && !init?.method)
				return response({
					...SETTINGS,
					settings: { ...SETTINGS.settings, excluded_service_ids: missingIds },
				});
			return baseFetch(input, init);
		},
	);
	renderSettings(fetchMock);
	await screen.findByLabelText("Exclude Netflix");
	expect(screen.getByText(/Exclusion limit reached/)).toBeTruthy();
	expect(
		(screen.getByLabelText("Exclude Netflix") as HTMLInputElement).disabled,
	).toBe(true);
	fireEvent.click(
		screen.getByLabelText("Exclude Service 99 (not in current options)"),
	);
	expect(screen.queryByText(/Exclusion limit reached/)).toBeNull();
	expect(
		(screen.getByLabelText("Exclude Netflix") as HTMLInputElement).disabled,
	).toBe(false);
	fireEvent.click(screen.getByLabelText("Exclude Netflix"));
	fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
	await screen.findByText("Settings saved.");
	const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
	expect(JSON.parse(String(put?.[1]?.body)).excluded_service_ids).toEqual([
		...missingIds.slice(1),
		8,
	]);
});

test("saved exclusion labels wait for regional options without losing the selection", async () => {
	const options = deferred<Response>();
	const baseFetch = routeAdminFetch();
	const fetchMock = vi.fn(
		async (input: RequestInfo | URL, init?: RequestInit) => {
			if (String(input) === "/api/v1/settings" && !init?.method)
				return response({
					...SETTINGS,
					settings: { ...SETTINGS.settings, excluded_service_ids: [8] },
				});
			if (String(input).includes("/api/v1/services")) return options.promise;
			return baseFetch(input, init);
		},
	);
	renderSettings(fetchMock);
	expect(
		(
			(await screen.findByLabelText(
				"Exclude Service 8 (loading options…)",
			)) as HTMLInputElement
		).checked,
	).toBe(true);
	expect(
		screen.queryByLabelText("Exclude Service 8 (not in current options)"),
	).toBeNull();
	options.resolve(response(SERVICES));
	expect(
		((await screen.findByLabelText("Exclude Netflix")) as HTMLInputElement)
			.checked,
	).toBe(true);
});

test.each([
	false,
	true,
])("missing exclusions remain visible when options fail and honor locks=%s", async (locked) => {
	const baseFetch = routeAdminFetch();
	const fetchMock = vi.fn(
		async (input: RequestInfo | URL, init?: RequestInit) => {
			if (String(input) === "/api/v1/settings" && !init?.method)
				return response({
					...SETTINGS,
					settings: {
						...SETTINGS.settings,
						excluded_service_ids: Array.from(
							{ length: 8 },
							(_, index) => 99 + index,
						),
					},
					locked_fields: locked ? ["excluded_service_ids"] : [],
				});
			if (String(input).includes("/api/v1/services")) return response({}, 502);
			return baseFetch(input, init);
		},
	);
	renderSettings(fetchMock);
	const checkbox = await screen.findByLabelText(
		"Exclude Service 99 (options unavailable)",
	);
	await screen.findByText(/Exclusion services are unavailable/);
	expect((checkbox as HTMLInputElement).checked).toBe(true);
	expect((checkbox.closest("fieldset") as HTMLFieldSetElement).disabled).toBe(
		locked,
	);
	expect(Boolean(screen.queryByText(/Exclusion limit reached/))).toBe(!locked);
	if (!locked) {
		fireEvent.click(checkbox);
		expect((checkbox as HTMLInputElement).checked).toBe(false);
		expect(screen.queryByText(/Exclusion limit reached/)).toBeNull();
	}
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

test.each([
	"request",
	"cancellation",
])("a late save cannot repopulate cache after the session changes during %s", async (phase) => {
	const lateSave = deferred<Response>();
	const cancellation = deferred<void>();
	const baseFetch = routeAdminFetch();
	const fetchMock = vi.fn(
		async (input: RequestInfo | URL, init?: RequestInit) => {
			if (String(input) === "/api/v1/settings" && init?.method === "PUT") {
				return lateSave.promise;
			}
			return baseFetch(input, init);
		},
	);
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	const cancelQueries = vi.spyOn(queryClient, "cancelQueries");
	if (phase === "cancellation")
		cancelQueries.mockImplementationOnce(() => cancellation.promise);
	queryClient.setQueryData(["auth", "me"], {
		id: 1,
		display_name: "Viewer A",
		avatar_url: null,
		is_admin: true,
	});
	renderSettings(fetchMock, queryClient);
	await screen.findByLabelText("Netflix");

	fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
	await waitFor(() =>
		expect(fetchMock).toHaveBeenCalledWith(
			"/api/v1/settings",
			expect.objectContaining({ method: "PUT" }),
		),
	);
	expect(queryClient.getMutationCache().getAll()).toHaveLength(1);
	if (phase === "cancellation") {
		lateSave.resolve(response({ ...SETTINGS, owner: "A-late" }));
		await waitFor(() => expect(cancelQueries).toHaveBeenCalledTimes(4));
		expect(
			cancelQueries.mock.calls.map(([filters]) => filters?.queryKey),
		).toEqual([["config"], ["home"], ["rails"], ["title"]]);
	}
	await setConfirmedSession(queryClient, {
		id: 2,
		display_name: "Viewer B",
		avatar_url: null,
		is_admin: true,
	});
	expect(queryClient.getMutationCache().getAll()).toEqual([]);

	if (phase === "request")
		lateSave.resolve(response({ ...SETTINGS, owner: "A-late" }));
	else cancellation.resolve();
	await waitFor(() =>
		expect(
			(
				screen.getByRole("button", {
					name: "Save settings",
				}) as HTMLButtonElement
			).disabled,
		).toBe(false),
	);
	expect(
		queryClient.getQueryData<{ owner?: string }>(["admin", "settings"])?.owner,
	).toBeUndefined();
	expect(
		queryClient.getQueryData(["discovery-settings-revision"]),
	).toBeUndefined();
});
