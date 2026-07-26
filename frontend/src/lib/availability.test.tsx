import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { MediaCard } from "../components/MediaCard";
import type { AvailabilityMap, MediaSummary } from "./api";
import { AvailabilityContext, useAvailabilityMap } from "./availability";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

function summary(id: number, title: string): MediaSummary {
	return {
		id,
		media_type: "movie",
		title,
		overview: "",
		poster_path: null,
		backdrop_path: null,
		year: 2020,
		vote_average: 7,
	};
}

// A view that batch-hydrates its items and hands the map to its cards.
function Harness({ items }: { items: MediaSummary[] }) {
	const map = useAvailabilityMap(items);
	return (
		<AvailabilityContext.Provider value={map.data ?? {}}>
			{items.map((item) => (
				<MediaCard
					key={`${item.media_type}-${item.id}-${item.title}`}
					item={item}
				/>
			))}
		</AvailabilityContext.Provider>
	);
}

test("hydrates badges from one deduped batch call after rendering", async () => {
	const bodies: unknown[] = [];
	const map: AvailabilityMap = {
		"movie:1": { status: "available", known: true },
		"movie:2": { status: "not_requested", known: true },
	};
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
			if (String(input).includes("/api/v1/availability")) {
				bodies.push(JSON.parse(String(init?.body)));
				return { ok: true, status: 200, json: async () => map } as Response;
			}
			return { ok: false, status: 404, json: async () => ({}) } as Response;
		}),
	);

	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	// id 1 appears twice — the batch must de-dupe it.
	const items = [summary(1, "One"), summary(2, "Two"), summary(1, "One again")];
	render(
		<QueryClientProvider client={queryClient}>
			<MemoryRouter>
				<Harness items={items} />
			</MemoryRouter>
		</QueryClientProvider>,
	);

	// The cards render immediately; the badge fills in after hydration resolves.
	expect(screen.getAllByText("One").length).toBeGreaterThan(0);
	expect((await screen.findAllByText("Available")).length).toBeGreaterThan(0);

	// One request, carrying the two distinct titles (id 1 de-duped).
	expect(bodies).toHaveLength(1);
	expect(bodies[0]).toEqual({
		items: [
			{ media_type: "movie", id: 1 },
			{ media_type: "movie", id: 2 },
		],
	});
	// not_requested renders no badge.
	expect(screen.queryByText("Requested")).toBeNull();
});
