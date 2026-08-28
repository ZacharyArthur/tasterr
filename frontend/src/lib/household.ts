import { useMutation, useQuery } from "@tanstack/react-query";
import {
	createHouseholdBlend,
	getHouseholdMembers,
	type HouseholdMember,
} from "./api";

export function useHouseholdMembers(userId: number) {
	return useQuery({
		queryKey: ["household-members", userId],
		queryFn: getHouseholdMembers,
		select: (members): HouseholdMember[] =>
			Array.isArray(members) ? members : [],
		staleTime: 60_000,
		retry: false,
	});
}

export function useHouseholdBlend() {
	return useMutation({
		mutationFn: (userIds: number[]) => createHouseholdBlend(userIds),
	});
}
