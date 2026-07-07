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
