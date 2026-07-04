// Thin typed wrapper over fetch. Types come from the generated OpenAPI schema
// (src/lib/api.gen.ts, regenerated via `just types`) — never hand-written twice.
import type { paths } from "./api.gen";

export type HealthResponse =
	paths["/api/v1/health"]["get"]["responses"]["200"]["content"]["application/json"];

async function getJson<T>(path: string): Promise<T> {
	const response = await fetch(path);
	if (!response.ok) {
		throw new Error(`GET ${path} failed: ${response.status}`);
	}
	return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
	return getJson<HealthResponse>("/api/v1/health");
}
