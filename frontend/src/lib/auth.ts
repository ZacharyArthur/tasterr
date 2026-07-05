import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getMe, logout } from "./api";

export const ME_QUERY_KEY = ["auth", "me"] as const;

export function useMe() {
	return useQuery({
		queryKey: ME_QUERY_KEY,
		queryFn: getMe,
		staleTime: 60_000,
		retry: false,
	});
}

export function useLogout() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: logout,
		onSettled: () => queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY }),
	});
}
