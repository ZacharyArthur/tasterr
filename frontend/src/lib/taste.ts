// Taste-engine hooks (M4): fire-and-forget signals, optimistic toggles,
// lazy explain, and the confirmed reset. Signal failures never disturb
// browsing — the worst case is an interaction the profile didn't learn from.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
	getExplain,
	type MediaType,
	postSignal,
	resetRecommendations,
} from "./api";

/** Fire-and-forget detail-open signal: errors are deliberately swallowed. */
export function recordDetailOpen(type: MediaType, id: number): void {
	postSignal(type, id, "detail_open").catch(() => {
		// A lost signal is invisible; browsing must never notice.
	});
}

/** Optimistic on/off signal (watchlist / not-interested): flips immediately,
 * posts the add or retraction, reverts on failure, and refreshes the home
 * feed on success so the personalized rails follow. */
export function useTasteToggle(
	type: MediaType,
	id: number,
	kind: "watchlist" | "not_interested",
	initial: boolean,
): { active: boolean; pending: boolean; toggle: () => void } {
	const queryClient = useQueryClient();
	const [active, setActive] = useState(initial);
	const mutation = useMutation({
		mutationFn: (wasActive: boolean) => postSignal(type, id, kind, wasActive),
		onError: (_error, wasActive) => setActive(wasActive), // revert the flip
		onSuccess: () => queryClient.invalidateQueries({ queryKey: ["home"] }),
	});
	const toggle = () => {
		const wasActive = active;
		setActive(!wasActive); // optimistic
		mutation.mutate(wasActive);
	};
	return { active, pending: mutation.isPending, toggle };
}

/** Lazy explain query — nothing is fetched until the user asks. */
export function useExplain(type: MediaType, id: number, enabled: boolean) {
	return useQuery({
		queryKey: ["explain", type, id],
		queryFn: () => getExplain(type, id),
		enabled,
		staleTime: 60_000,
	});
}

export function useResetRecommendations() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: resetRecommendations,
		onSuccess: () => queryClient.invalidateQueries({ queryKey: ["home"] }),
	});
}
