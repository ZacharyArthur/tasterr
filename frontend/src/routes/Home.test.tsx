import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { HealthResponse } from "../lib/api";
import { Home } from "./Home";

afterEach(() => {
	vi.unstubAllGlobals();
});

test("renders backend health from /api/v1/health", async () => {
	const body = {
		status: "ok",
		tmdb_configured: true,
		seerr_configured: false,
	} satisfies HealthResponse;
	const response = {
		ok: true,
		status: 200,
		json: async () => body,
	} as Response;
	const fetchMock = vi.fn(async () => response);
	vi.stubGlobal("fetch", fetchMock);

	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={queryClient}>
			<Home />
		</QueryClientProvider>,
	);

	expect(await screen.findByText("ok")).toBeTruthy();
	expect(screen.getByText("configured")).toBeTruthy();
	expect(screen.getByText("not configured")).toBeTruthy();
	expect(fetchMock).toHaveBeenCalledWith("/api/v1/health");
});
