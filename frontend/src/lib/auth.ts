import {
	type QueryClient,
	useMutation,
	useQuery,
	useQueryClient,
} from "@tanstack/react-query";
import { getMe, logout, type User } from "./api";

export const ME_QUERY_KEY = ["auth", "me"] as const;
const sessionEpochs = new WeakMap<QueryClient, number>();

function isMeQuery(queryKey: readonly unknown[]): boolean {
	return (
		queryKey.length === ME_QUERY_KEY.length &&
		queryKey.every((part, index) => part === ME_QUERY_KEY[index])
	);
}

function getSessionEpoch(queryClient: QueryClient): number {
	return sessionEpochs.get(queryClient) ?? 0;
}

export function isSessionCurrent(
	queryClient: QueryClient,
	epoch: number,
): boolean {
	return getSessionEpoch(queryClient) === epoch;
}

export function captureSession(queryClient: QueryClient): number {
	return getSessionEpoch(queryClient);
}

async function clearSessionState(
	queryClient: QueryClient,
	cancelMe: boolean,
): Promise<void> {
	sessionEpochs.set(queryClient, getSessionEpoch(queryClient) + 1);
	queryClient.getMutationCache().clear();
	await queryClient.cancelQueries({
		predicate: ({ queryKey }) => cancelMe || !isMeQuery(queryKey),
	});
	queryClient.removeQueries({
		predicate: ({ queryKey }) => !isMeQuery(queryKey),
	});
}

export async function setConfirmedSession(
	queryClient: QueryClient,
	user: User | null,
): Promise<void> {
	await clearSessionState(queryClient, true);
	queryClient.setQueryData(ME_QUERY_KEY, user);
}

export function useMe() {
	const queryClient = useQueryClient();
	return useQuery({
		queryKey: ME_QUERY_KEY,
		queryFn: async ({ signal }) => {
			const user = await getMe();
			const currentUser = queryClient.getQueryData<User | null>(ME_QUERY_KEY);
			if (
				!signal.aborted &&
				currentUser !== undefined &&
				currentUser?.id !== user?.id
			) {
				await clearSessionState(queryClient, false);
			}
			return user;
		},
		staleTime: 60_000,
		retry: false,
	});
}

export function useLogout() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: logout,
		onMutate: () => captureSession(queryClient),
		onSuccess: (_data, _variables, sessionEpoch) => {
			if (isSessionCurrent(queryClient, sessionEpoch)) {
				return setConfirmedSession(queryClient, null);
			}
		},
	});
}
