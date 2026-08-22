import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
	getRegions,
	getServices,
	getSettings,
	type RuntimeSettings,
	saveSettings,
	testConnection,
} from "./api";
import { captureSession, isSessionCurrent } from "./auth";

export const SETTINGS_QUERY_KEY = ["admin", "settings"] as const;

export function useSettings(enabled = true) {
	return useQuery({
		queryKey: SETTINGS_QUERY_KEY,
		queryFn: getSettings,
		enabled,
	});
}

export function useRegions(enabled = true) {
	return useQuery({
		queryKey: ["admin", "regions"],
		queryFn: getRegions,
		enabled,
		staleTime: 24 * 60 * 60 * 1000,
	});
}

export function useServices(region: string, enabled = true) {
	return useQuery({
		queryKey: ["admin", "services", region],
		queryFn: () => getServices(region),
		enabled: enabled && region.length === 2,
		staleTime: 24 * 60 * 60 * 1000,
	});
}

export function useSaveSettings() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (settings: RuntimeSettings) => saveSettings(settings),
		onMutate: () => captureSession(queryClient),
		onSuccess: (response, _settings, sessionEpoch) => {
			if (!isSessionCurrent(queryClient, sessionEpoch)) return;
			queryClient.setQueryData(SETTINGS_QUERY_KEY, response);
			queryClient.setQueryData(["config"], (current: object | undefined) =>
				current
					? { ...current, appearance: response.settings.appearance }
					: current,
			);
			for (const key of [["config"], ["home"], ["rails"], ["title"]]) {
				void queryClient.invalidateQueries({ queryKey: key });
			}
		},
	});
}

export function useConnectionTest() {
	return useMutation({ mutationFn: testConnection });
}
