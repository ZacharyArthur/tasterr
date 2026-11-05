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
import type { IntegrationsResponse } from "../lib/api";
import { setConfirmedSession } from "../lib/auth";
import { Settings } from "./Settings";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

const SETTINGS = {
	configured_sign_in_methods: ["plex", "jellyfin", "seerr"],
	sign_in_link_counts: [],
	settings: {
		region: "US",
		language: "en-US",
		service_ids: [8],
		disabled_rail_types: [],
		disabled_sign_in_methods: [],
		appearance: { theme: "dark", accent: "crimson" },
		hide_library_items: false,
		hide_watched_items: true,
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
		if (url === "/api/v1/integrations")
			return response({
				seerr: {
					configured: true,
					media_server: "unknown",
					plex: null,
					jellyfin: null,
					local: null,
				},
				plex_server_pinned: false,
				jellyfin_configured: true,
			});
		if (url === "/api/v1/regions") return response(REGIONS);
		if (url === "/api/v1/languages")
			return response({ languages: ["en-US", "es-ES"] });
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

test("all four connection checks render readable labels and returned details", async () => {
	const base = routeAdminFetch();
	const fetchMock = vi.fn(
		async (input: RequestInfo | URL, init?: RequestInit) => {
			if (String(input) === "/api/v1/connection-test") {
				const { target } = JSON.parse(String(init?.body)) as { target: string };
				return response({
					target,
					ok: target !== "jellyfin",
					detail: "Returned detail",
				});
			}
			return base(input, init);
		},
	);
	renderSettings(fetchMock);
	for (const label of ["TMDB", "Seerr", "Plex", "Jellyfin"]) {
		fireEvent.click(
			await screen.findByRole("button", { name: `Test ${label}` }),
		);
		expect(await screen.findByText(`${label}: Returned detail`)).toBeTruthy();
	}
});

test.each([
	{
		server: "jellyfin",
		plex: false,
		jellyfin: true,
		local: true,
		pinned: false,
		configured: true,
		warnings: [true, false, false],
	},
	{
		server: "plex",
		plex: true,
		jellyfin: false,
		local: true,
		pinned: true,
		configured: true,
		warnings: [false, true, false],
	},
	{
		server: "plex",
		plex: true,
		jellyfin: false,
		local: false,
		pinned: true,
		configured: true,
		warnings: [false, true, true],
	},
	{
		server: "unknown",
		plex: null,
		jellyfin: null,
		local: null,
		pinned: false,
		configured: true,
		warnings: [false, false, false],
	},
	{
		server: "plex",
		plex: true,
		jellyfin: false,
		local: false,
		pinned: true,
		configured: false,
		warnings: [false, false, false],
	},
] as const)(
	"Seerr integration warnings: $server / local $local",
	async (values) => {
		const summary: IntegrationsResponse = {
			seerr: {
				configured: true,
				media_server: values.server,
				plex: values.plex,
				jellyfin: values.jellyfin,
				local: values.local,
			},
			plex_server_pinned: values.pinned,
			jellyfin_configured: values.configured,
		};
		const base = routeAdminFetch();
		renderSettings(
			vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
				String(input) === "/api/v1/integrations"
					? response(summary)
					: base(input, init),
			),
		);
		expect(
			await screen.findByRole("heading", { name: "Seerr integration" }),
		).toBeTruthy();
		expect(screen.getByText(`Media server: ${values.server}`)).toBeTruthy();
		for (const [index, text] of [
			/Plex sign-in and Plex linking will fail/,
			/Members who only use Jellyfin need/,
			/These members cannot request unless/,
		].entries()) {
			expect(!!screen.queryByText(text)).toBe(values.warnings[index]);
		}
		if (values.server === "unknown")
			expect(
				screen.getByText(
					/Plex login: Unknown; Jellyfin login: Unknown; Local login: Unknown/,
				),
			).toBeTruthy();
	},
);

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
		language: "en-US",
		service_ids: [8, 9],
		disabled_rail_types: ["popular"],
		disabled_sign_in_methods: [],
		appearance: { theme: "light", accent: "azure" },
		hide_library_items: false,
		hide_watched_items: true,
		excluded_service_ids: [],
	});
	for (const key of [["config"], ["home"], ["rails"], ["title"]]) {
		expect(queryClient.getQueryState(key)?.isInvalidated ?? true).toBe(true);
	}
	expect(screen.queryByLabelText(/key|token|url|secret/i)).toBeNull();
});

test.each([false, true])(
	"sign-in methods respect configuration and lock: %s",
	async (locked) => {
		const base = routeAdminFetch();
		const fetchMock = vi.fn(
			async (input: RequestInfo | URL, init?: RequestInit) => {
				if (String(input) === "/api/v1/settings" && !init?.method)
					return response({
						...SETTINGS,
						configured_sign_in_methods: ["plex", "jellyfin"],
						locked_fields: locked ? ["disabled_sign_in_methods"] : [],
						settings: {
							...SETTINGS.settings,
							disabled_sign_in_methods: ["plex"],
						},
						sign_in_link_counts: [
							{ methods: ["plex"], count: 2 },
							{ methods: ["jellyfin"], count: 1 },
							{ methods: ["plex", "jellyfin"], count: 3 },
							{ methods: [], count: 1 },
						],
					});
				return base(input, init);
			},
		);
		renderSettings(fetchMock);
		const plex = await screen.findByRole("checkbox", { name: "Plex" });
		const jellyfin = screen.getByRole("checkbox", { name: "Jellyfin" });
		expect(
			(
				screen.getByRole("checkbox", {
					name: "Seerr (Not configured)",
				}) as HTMLInputElement
			).disabled,
		).toBe(true);
		expect((jellyfin as HTMLInputElement).checked).toBe(true);
		expect((jellyfin as HTMLInputElement).disabled).toBe(true);
		expect((plex as HTMLInputElement).disabled).toBe(locked);
		expect(screen.getByText(/3 members would have no way/)).toBeTruthy();
		if (locked) {
			expect(
				screen.getByText(/controlled by TASTERR_SIGN_IN_METHODS/),
			).toBeTruthy();
		} else {
			fireEvent.click(plex);
			expect(screen.getByText(/1 member would have no way/)).toBeTruthy();
			fireEvent.click(jellyfin);
			expect((plex as HTMLInputElement).disabled).toBe(true);
			expect(screen.getByText(/2 members would have no way/)).toBeTruthy();
			fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
			await screen.findByText("Settings saved.");
			const put = fetchMock.mock.calls.find(
				([, init]) => init?.method === "PUT",
			);
			expect(
				JSON.parse(String(put?.[1]?.body)).disabled_sign_in_methods,
			).toEqual(["jellyfin"]);
		}
	},
);

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

test("labels metadata languages, retains a saved code missing from options, and saves the selection", async () => {
	const baseFetch = routeAdminFetch();
	const fetchMock = vi.fn(
		async (input: RequestInfo | URL, init?: RequestInit) => {
			if (String(input) === "/api/v1/settings" && !init?.method) {
				return response({
					...SETTINGS,
					settings: { ...SETTINGS.settings, language: "fr-CA" },
				});
			}
			return baseFetch(input, init);
		},
	);
	renderSettings(fetchMock);
	const select = (await screen.findByLabelText(
		"Metadata language",
	)) as HTMLSelectElement;
	const names = new Intl.DisplayNames(undefined, { type: "language" });
	expect(select.value).toBe("fr-CA");
	expect(
		await screen.findByRole("option", { name: `${names.of("es-ES")} (es-ES)` }),
	).toBeTruthy();
	expect(
		screen.getByRole("option", { name: `${names.of("fr-CA")} (fr-CA)` }),
	).toBeTruthy();
	fireEvent.change(select, { target: { value: "es-ES" } });
	expect(
		screen.getByRole("option", { name: `${names.of("fr-CA")} (fr-CA)` }),
	).toBeTruthy();
	fireEvent.change(select, { target: { value: "fr-CA" } });
	expect(select.value).toBe("fr-CA");
	expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(
		false,
	);
	fireEvent.change(select, { target: { value: "es-ES" } });
	fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
	await screen.findByText("Settings saved.");
	const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
	expect(JSON.parse(String(put?.[1]?.body)).language).toBe("es-ES");
});

test("keeps the saved metadata language selectable when choices fail", async () => {
	const baseFetch = routeAdminFetch();
	renderSettings(
		vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
			String(input) === "/api/v1/languages"
				? response({}, 503)
				: baseFetch(input, init),
		),
	);
	const select = (await screen.findByLabelText(
		"Metadata language",
	)) as HTMLSelectElement;
	expect(select.value).toBe("en-US");
	expect(
		await screen.findByText(/Language options are unavailable/),
	).toBeTruthy();
	fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
	await screen.findByText("Settings saved.");
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

test.each([false, true])(
	"watched hiding renders its effective value and lock=%s",
	async (locked) => {
		const baseFetch = routeAdminFetch();
		const fetchMock = vi.fn(
			async (input: RequestInfo | URL, init?: RequestInit) => {
				if (String(input) === "/api/v1/settings" && !init?.method) {
					return response({
						...SETTINGS,
						settings: { ...SETTINGS.settings, hide_watched_items: !locked },
						locked_fields: locked ? ["hide_watched_items"] : [],
					});
				}
				return baseFetch(input, init);
			},
		);
		renderSettings(fetchMock);
		const checkbox = (await screen.findByLabelText(
			"Hide titles members have watched",
		)) as HTMLInputElement;
		expect(checkbox.checked).toBe(!locked);
		expect(checkbox.disabled).toBe(locked);
		expect(screen.getByText(/Each member's own watched titles/)).toBeTruthy();
		expect(screen.getByText(/Not interested always hides/)).toBeTruthy();
		expect(screen.getByText(/Unknown availability stays visible/)).toBeTruthy();
		if (locked) {
			expect(
				screen.getByText(
					"Watched-title hiding is controlled by an environment variable.",
				),
			).toBeTruthy();
		} else {
			fireEvent.click(checkbox);
			expect(checkbox.checked).toBe(false);
		}
		fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
		await screen.findByText("Settings saved.");
		const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
		expect(JSON.parse(String(put?.[1]?.body)).hide_watched_items).toBe(false);
	},
);

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

test.each([false, true])(
	"missing exclusions remain visible when options fail and honor locks=%s",
	async (locked) => {
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
				if (String(input).includes("/api/v1/services"))
					return response({}, 502);
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
		expect(Boolean(screen.queryByText(/Exclusion limit reached/))).toBe(
			!locked,
		);
		if (!locked) {
			fireEvent.click(checkbox);
			expect((checkbox as HTMLInputElement).checked).toBe(false);
			expect(screen.queryByText(/Exclusion limit reached/)).toBeNull();
		}
	},
);

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

test.each(["request", "cancellation"])(
	"a late save cannot repopulate cache after the session changes during %s",
	async (phase) => {
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
			await waitFor(() => expect(cancelQueries).toHaveBeenCalledTimes(7));
			expect(
				cancelQueries.mock.calls.map(([filters]) => filters?.queryKey),
			).toEqual([
				["config"],
				["home"],
				["rails"],
				["title"],
				["search"],
				["admin", "regions"],
				["admin", "services"],
			]);
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
			queryClient.getQueryData<{ owner?: string }>(["admin", "settings"])
				?.owner,
		).toBeUndefined();
		expect(
			queryClient.getQueryData(["discovery-settings-revision"]),
		).toBeUndefined();
	},
);
