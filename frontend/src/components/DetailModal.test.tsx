import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { DetailModal } from "./DetailModal";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

const DETAIL = {
	id: 42,
	media_type: "movie",
	title: "Deep Movie",
	overview: "An overview.",
	poster_path: null,
	backdrop_path: "/b.jpg",
	year: 2020,
	vote_average: 7,
	tagline: "A tagline",
	genres: [{ id: 18, name: "Drama" }],
	runtime: 120,
	release_date: "2020-01-01",
	certification: "PG-13",
	logo_path: null,
	trailer: {
		key: "abc123",
		site: "YouTube",
		type: "Trailer",
		name: "T",
		official: true,
	},
	cast: [{ id: 9, name: "Actor One", role: "Hero", profile_path: null }],
	crew: [],
	watch: {
		flatrate: [{ provider_id: 8, name: "Netflix", logo_path: null }],
		rent: [],
		buy: [],
		free: [],
	},
	recommendations: [],
	similar: [],
	seasons: [],
	number_of_seasons: null,
};

function renderModal() {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={queryClient}>
			<MemoryRouter initialEntries={["/title/movie/42"]}>
				<Routes>
					<Route path="/title/:type/:id" element={<DetailModal />} />
				</Routes>
			</MemoryRouter>
		</QueryClientProvider>,
	);
}

test("renders the title detail sections", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(
			async () =>
				({ ok: true, status: 200, json: async () => DETAIL }) as Response,
		),
	);
	renderModal();

	expect(
		await screen.findByRole("heading", { name: "Deep Movie" }),
	).toBeTruthy();
	expect(screen.getByText("An overview.")).toBeTruthy();
	expect(screen.getByText("Where & how to watch")).toBeTruthy();
	expect(screen.getByText("Netflix")).toBeTruthy();
	expect(screen.getByText("Actor One")).toBeTruthy();
	expect(screen.getByRole("button", { name: "Close" })).toBeTruthy();
});
