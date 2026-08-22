import {
	keepPreviousData,
	useMutation,
	useQuery,
	useQueryClient,
} from "@tanstack/react-query";
import { createContext, useContext } from "react";
import {
	type Availability,
	type AvailabilityMap,
	createRequest,
	getConfig,
	type MediaDetail,
	type MediaSummary,
	type MediaType,
	postAvailability,
} from "./api";
import { captureSession, isSessionCurrent } from "./auth";

export function availabilityKey(mediaType: MediaType, id: number): string {
	return `${mediaType}:${id}`;
}

// Cards read their badge from this map, populated by the view's batch hydration.
// Default {} means "no data yet" — badges simply don't render until it fills.
export const AvailabilityContext = createContext<AvailabilityMap>({});

export function useConfig() {
	// Runtime appearance shares this key; a successful admin save explicitly
	// invalidates it while ordinary browsing treats it as stable.
	return useQuery({
		queryKey: ["config"],
		queryFn: getConfig,
		staleTime: Number.POSITIVE_INFINITY,
	});
}

/** Batch-hydrate availability for a set of titles after the view has rendered. */
export function useAvailabilityMap(items: MediaSummary[]) {
	// De-dupe (a title can appear in several rails) and sort, so the query key is
	// stable regardless of render order and repeats collapse to one request.
	const unique = new Map(
		items.map(
			(item) => [availabilityKey(item.media_type, item.id), item] as const,
		),
	);
	const pairs = [...unique.values()].map((item) => ({
		media_type: item.media_type,
		id: item.id,
	}));
	const keys = [...unique.keys()].sort();
	return useQuery({
		queryKey: ["availability", keys],
		queryFn: () => postAvailability(pairs),
		enabled: pairs.length > 0, // empty view → no Seerr call; browsing never waits
		staleTime: 60_000,
		// Infinite scroll grows the id set (a new key). Keep the prior badges up
		// while the larger batch loads instead of flashing them off.
		placeholderData: keepPreviousData,
	});
}

export function useAvailabilityFor(item: {
	media_type: MediaType;
	id: number;
}): Availability | undefined {
	const map = useContext(AvailabilityContext);
	return map[availabilityKey(item.media_type, item.id)];
}

/** A title can be requested only when Seerr confirmed it is not yet in the library.
 * Unknown (Seerr unreachable) is not actionable; available/pending/etc. are not. */
export function isRequestable(
	availability: Availability | null | undefined,
): boolean {
	return (
		availability?.known === true && availability.status === "not_requested"
	);
}

export function useRequest(type: MediaType, id: number) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: () => createRequest(type, id),
		onMutate: () => captureSession(queryClient),
		onSuccess: (response, _variables, sessionEpoch) => {
			if (!isSessionCurrent(queryClient, sessionEpoch)) return;
			if (response.status === "ok" && response.availability) {
				const next = response.availability;
				// Flip this title's detail badge immediately, and let card badges
				// refetch from the authoritative server state.
				queryClient.setQueryData<MediaDetail>(["title", type, id], (old) =>
					old ? { ...old, availability: next } : old,
				);
				void queryClient.invalidateQueries({ queryKey: ["availability"] });
			}
		},
	});
}
