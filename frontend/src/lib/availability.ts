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
	getDestinations,
	type MediaDetail,
	type MediaSummary,
	type MediaType,
	postAvailability,
	type RequestSelection,
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

/** Shared within the current session: destinations depend on type, not title. */
export function useDestinations(type: MediaType, id: number, enabled = true) {
	return useQuery({
		queryKey: ["destinations", type],
		queryFn: () => getDestinations(type, id),
		enabled,
		staleTime: 60_000,
		retry: false,
	});
}

export function variantRequestable(
	availability: Availability | null | undefined,
	is4k: boolean,
): boolean {
	if (!availability?.known) return false;
	const status = is4k
		? (availability.four_k_status ?? availability.status)
		: (availability.regular_status ?? availability.status);
	return status === "not_requested";
}

export function useRequest(type: MediaType, id: number) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (destination?: RequestSelection) =>
			createRequest(type, id, destination),
		onMutate: () => captureSession(queryClient),
		onSuccess: (response, variables, sessionEpoch) => {
			if (!isSessionCurrent(queryClient, sessionEpoch)) return;
			if (response.status === "ok" && response.availability) {
				const next = response.availability;
				// Flip this title's detail badge immediately, and let card badges
				// refetch from the authoritative server state.
				queryClient.setQueryData<MediaDetail>(["title", type, id], (old) => {
					if (!old) return old;
					const previous = old.availability;
					const regular = variables?.is_4k
						? (previous?.regular_status ?? previous?.status ?? "not_requested")
						: next.status;
					const fourK = variables?.is_4k
						? next.status
						: (previous?.four_k_status ?? "not_requested");
					const rank = [
						"not_requested",
						"pending",
						"processing",
						"partial",
						"available",
					];
					const status =
						rank.indexOf(regular) >= rank.indexOf(fourK) ? regular : fourK;
					return {
						...old,
						availability: {
							...next,
							status,
							regular_status: regular,
							four_k_status: fourK,
							playback: previous?.playback ?? next.playback,
						},
					};
				});
				void queryClient.invalidateQueries({ queryKey: ["availability"] });
			}
		},
	});
}
