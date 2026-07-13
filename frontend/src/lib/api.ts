// Thin typed wrapper over fetch. Types come from the generated OpenAPI schema
// (src/lib/api.gen.ts, regenerated via `just types`) — never hand-written twice.
import type { components, paths } from "./api.gen";

export type HealthResponse =
	paths["/api/v1/health"]["get"]["responses"]["200"]["content"]["application/json"];
export type User = components["schemas"]["UserResponse"];
export type PinCreateResponse = components["schemas"]["PinCreateResponse"];
export type PinPollResponse = components["schemas"]["PinPollResponse"];
export type PublicConfig = components["schemas"]["PublicConfig"];
export type HomeFeed = components["schemas"]["HomeFeed"];
export type RailsPage = components["schemas"]["RailsPage"];
export type Rail = components["schemas"]["Rail"];
export type HeroSlide = components["schemas"]["HeroSlide"];
export type MediaSummary = components["schemas"]["MediaSummary"];
export type MediaDetail = components["schemas"]["MediaDetail"];
export type SearchResponse = components["schemas"]["SearchResponse"];
export type MediaType = MediaSummary["media_type"];
export type Availability = components["schemas"]["Availability"];
export type AvailabilityStatus = Availability["status"];
export type RequestResponse = components["schemas"]["RequestResponse"];
/** Keyed by `"<media_type>:<id>"`, the shape `POST /availability` returns. */
export type AvailabilityMap = Record<string, Availability>;
export type SignalKind = components["schemas"]["SignalBody"]["kind"];
export type SignalResponse = components["schemas"]["SignalResponse"];
export type ExplainResponse = components["schemas"]["ExplainResponse"];
export type ResetResponse = components["schemas"]["ResetResponse"];
export type TasteFlags = components["schemas"]["TasteFlags"];
export type Appearance = components["schemas"]["Appearance"];
export type RuntimeSettings = components["schemas"]["RuntimeSettings"];
export type SettingsResponse = components["schemas"]["SettingsResponse"];
export type RegionOption = components["schemas"]["RegionOption"];
export type RegionsResponse = components["schemas"]["RegionsResponse"];
export type ServiceOption = components["schemas"]["ServiceOption"];
export type ServicesResponse = components["schemas"]["ServicesResponse"];
export type ConnectionTarget = components["schemas"]["ConnectionTarget"];
export type ConnectionTestResponse =
	components["schemas"]["ConnectionTestResponse"];

export class ApiError extends Error {
	readonly status: number;

	constructor(status: number, detail: string) {
		super(detail);
		this.name = "ApiError";
		this.status = status;
	}
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	const response = await fetch(path, init);
	if (!response.ok) {
		let detail = `Request failed (${response.status})`;
		try {
			const body = (await response.json()) as { detail?: unknown };
			if (typeof body.detail === "string") {
				detail = body.detail;
			}
		} catch {
			// Non-JSON error body: keep the generic message.
		}
		throw new ApiError(response.status, detail);
	}
	if (response.status === 204) {
		return undefined as T;
	}
	return (await response.json()) as T;
}

function postJson<T>(path: string, body?: unknown): Promise<T> {
	return request<T>(path, {
		method: "POST",
		...(body === undefined
			? {}
			: {
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify(body),
				}),
	});
}

function putJson<T>(path: string, body: unknown): Promise<T> {
	return request<T>(path, {
		method: "PUT",
		credentials: "same-origin",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function getHealth(): Promise<HealthResponse> {
	return request<HealthResponse>("/api/v1/health");
}

/** null = not signed in — 401 is auth state here, not an error. */
export async function getMe(): Promise<User | null> {
	try {
		return await request<User>("/api/v1/auth/me");
	} catch (error) {
		if (error instanceof ApiError && error.status === 401) {
			return null;
		}
		throw error;
	}
}

export function createPlexPin(): Promise<PinCreateResponse> {
	return postJson<PinCreateResponse>("/api/v1/auth/plex/pin");
}

export function pollPlexPin(pinId: string): Promise<PinPollResponse> {
	return request<PinPollResponse>(
		`/api/v1/auth/plex/pin/${encodeURIComponent(pinId)}`,
	);
}

export function loginLocal(email: string, password: string): Promise<User> {
	return postJson<User>("/api/v1/auth/local", { email, password });
}

export function logout(): Promise<void> {
	return postJson<void>("/api/v1/auth/logout");
}

export function getHome(): Promise<HomeFeed> {
	return request<HomeFeed>("/api/v1/home");
}

export function getRails(cursor: number): Promise<RailsPage> {
	return request<RailsPage>(`/api/v1/rails?cursor=${cursor}`);
}

export function getTitle(type: MediaType, id: number): Promise<MediaDetail> {
	return request<MediaDetail>(`/api/v1/title/${type}/${id}`);
}

export function searchTitles(query: string): Promise<SearchResponse> {
	return request<SearchResponse>(
		`/api/v1/search?q=${encodeURIComponent(query)}`,
	);
}

export function getConfig(): Promise<PublicConfig> {
	return request<PublicConfig>("/api/v1/config");
}

export function getSettings(): Promise<SettingsResponse> {
	return request<SettingsResponse>("/api/v1/settings");
}

export function saveSettings(
	settings: RuntimeSettings,
): Promise<SettingsResponse> {
	return putJson<SettingsResponse>("/api/v1/settings", settings);
}

export function getRegions(): Promise<RegionsResponse> {
	return request<RegionsResponse>("/api/v1/regions");
}

export function getServices(region: string): Promise<ServicesResponse> {
	return request<ServicesResponse>(
		`/api/v1/services?region=${encodeURIComponent(region.toUpperCase())}`,
	);
}

export function testConnection(
	target: ConnectionTarget,
): Promise<ConnectionTestResponse> {
	return request<ConnectionTestResponse>("/api/v1/connection-test", {
		method: "POST",
		credentials: "same-origin",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ target }),
	});
}

/** Batch-hydrate library status for the given titles (SPEC §6). */
export function postAvailability(
	items: { media_type: MediaType; id: number }[],
): Promise<AvailabilityMap> {
	return postJson<AvailabilityMap>("/api/v1/availability", { items });
}

/** Request a title as the current user; returns a discriminated outcome. */
export function createRequest(
	mediaType: MediaType,
	tmdbId: number,
): Promise<RequestResponse> {
	return postJson<RequestResponse>("/api/v1/request", {
		media_type: mediaType,
		tmdb_id: tmdbId,
	});
}

/** Record (or retract, for the toggle kinds) an interaction signal (M4). */
export function postSignal(
	mediaType: MediaType,
	tmdbId: number,
	kind: SignalKind,
	retract = false,
): Promise<SignalResponse> {
	return postJson<SignalResponse>("/api/v1/signals", {
		media_type: mediaType,
		tmdb_id: tmdbId,
		kind,
		retract,
	});
}

/** "Why am I seeing this?" — reasons from the caller's own profile. */
export function getExplain(
	type: MediaType,
	id: number,
): Promise<ExplainResponse> {
	return request<ExplainResponse>(
		`/api/v1/recommendations/explain?type=${type}&id=${id}`,
	);
}

/** Wipe the caller's signals + profile and re-seed from Seerr history. */
export function resetRecommendations(): Promise<ResetResponse> {
	return postJson<ResetResponse>("/api/v1/recommendations/reset");
}
