import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
	getHome,
	getRails,
	getTitle,
	type MediaType,
	searchTitles,
} from "./api";

export function useHome() {
	return useQuery({ queryKey: ["home"], queryFn: getHome, staleTime: 60_000 });
}

export function useRails() {
	return useInfiniteQuery({
		queryKey: ["rails"],
		queryFn: ({ pageParam }) => getRails(pageParam),
		initialPageParam: 0,
		getNextPageParam: (last) => last.next_cursor ?? undefined,
		staleTime: 60_000,
	});
}

export function useTitle(type: MediaType, id: number) {
	return useQuery({
		queryKey: ["title", type, id],
		queryFn: () => getTitle(type, id),
		enabled: Number.isFinite(id) && id > 0,
	});
}

export function useSearch(query: string) {
	const trimmed = query.trim();
	return useQuery({
		queryKey: ["search", trimmed],
		queryFn: () => searchTitles(trimmed),
		enabled: trimmed.length > 0,
	});
}
