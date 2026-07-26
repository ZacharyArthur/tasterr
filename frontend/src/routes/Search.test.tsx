import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { Search } from "./Search";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

function renderSearch(entry: string) {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={queryClient}>
			<MemoryRouter initialEntries={[entry]}>
				<Search />
			</MemoryRouter>
		</QueryClientProvider>,
	);
}

test("an empty query issues no fetch", () => {
	const fetchMock = vi.fn();
	vi.stubGlobal("fetch", fetchMock);
	renderSearch("/search");
	expect(fetchMock).not.toHaveBeenCalled();
});

test("a query renders matching results", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(
			async () =>
				({
					ok: true,
					status: 200,
					json: async () => ({
						results: [
							{
								id: 603,
								media_type: "movie",
								title: "The Matrix",
								overview: "",
								poster_path: "/matrix.jpg",
								backdrop_path: null,
								year: 1999,
								vote_average: 8,
							},
						],
					}),
				}) as Response,
		),
	);
	renderSearch("/search?q=matrix");
	expect(await screen.findByText("The Matrix")).toBeTruthy();
});
