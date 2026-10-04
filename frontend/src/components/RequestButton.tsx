import { useState } from "react";
import type { Availability, MediaType, RequestDestination } from "../lib/api";
import {
	isRequestable,
	useConfig,
	useDestinations,
	useRequest,
} from "../lib/availability";

export function RequestButton({
	type,
	id,
	availability,
}: {
	type: MediaType;
	id: number;
	availability?: Availability | null;
}) {
	const config = useConfig();
	const destinations = useDestinations(type, id);
	const request = useRequest(type, id);
	const [pickerOpen, setPickerOpen] = useState(false);
	const [selection, setSelection] = useState<RequestDestination | null>(null);

	// Seerr off entirely (or its config not yet known) → no request affordance.
	if (!config.data?.seerr_configured) {
		return null;
	}

	const result = request.data;
	if (result?.status === "re_auth_required") {
		return (
			<p role="alert" className="text-sm text-status-warning">
				Your Seerr session expired — sign in again to request.
			</p>
		);
	}
	if (result && result.status !== "ok") {
		// Seerr down or the request was denied — hand off to Seerr when we can.
		return result.seerr_url ? (
			<a
				href={result.seerr_url}
				target="_blank"
				rel="noreferrer"
				className="inline-flex min-h-11 w-fit items-center gap-1 rounded bg-app-accent px-3 py-1.5 text-sm font-medium text-white hover:brightness-110 focus-visible:outline-2 focus-visible:outline-app-text"
			>
				Request in Seerr ↗
			</a>
		) : (
			<p className="text-sm text-status-error">
				Couldn’t send the request. Try again later.
			</p>
		);
	}
	if (request.isSuccess) {
		return <p className="text-sm font-medium text-emerald-400">Requested ✓</p>;
	}

	// Already available / requested / status unknown → the badge conveys it; no button.
	if (!isRequestable(availability)) {
		return null;
	}

	const options = destinations.data ?? [];
	const hasChoice =
		options.length > 1 ||
		options.some(
			(option) =>
				option.quality_profiles.length > 1 || option.root_folders.length > 1,
		);
	const active =
		selection ?? options.find((option) => option.is_default) ?? options[0];

	function selectServer(serverId: number) {
		const next = options.find((option) => option.server_id === serverId);
		if (next) setSelection(next);
	}

	function submit() {
		if (hasChoice && !pickerOpen) {
			setPickerOpen(true);
			return;
		}
		if (pickerOpen && active) {
			request.mutate({
				server_id: active.server_id,
				profile_id: active.default_profile_id,
				root_folder: active.default_root_folder,
			});
			return;
		}
		request.mutate(undefined);
	}

	return (
		<div className="flex flex-col items-start gap-2">
			{pickerOpen && active && (
				<div className="flex flex-col gap-2 text-sm">
					<label className="flex flex-col gap-1">
						<span className="text-xs text-app-text-dim">Server</span>
						<select
							value={active.server_id}
							onChange={(event) => selectServer(Number(event.target.value))}
							className="rounded border border-app-border bg-app-surface px-2 py-1"
						>
							{options.map((option) => (
								<option key={option.server_id} value={option.server_id}>
									{option.server_name}
								</option>
							))}
						</select>
					</label>
					<label className="flex flex-col gap-1">
						<span className="text-xs text-app-text-dim">Quality Profile</span>
						<select
							value={active.default_profile_id}
							onChange={(event) =>
								setSelection({
									...active,
									default_profile_id: Number(event.target.value),
								})
							}
							className="rounded border border-app-border bg-app-surface px-2 py-1"
						>
							{active.quality_profiles.map((profile) => (
								<option key={profile.id} value={profile.id}>
									{profile.name}
								</option>
							))}
						</select>
					</label>
					<label className="flex flex-col gap-1">
						<span className="text-xs text-app-text-dim">Root Folder</span>
						<select
							value={active.default_root_folder}
							onChange={(event) =>
								setSelection({
									...active,
									default_root_folder: event.target.value,
								})
							}
							className="rounded border border-app-border bg-app-surface px-2 py-1"
						>
							{active.root_folders.map((folder) => (
								<option key={folder.id} value={folder.path}>
									{folder.path}
								</option>
							))}
						</select>
					</label>
				</div>
			)}
			<button
				type="button"
				onClick={submit}
				disabled={request.isPending}
				className="w-fit rounded bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-60"
			>
				{request.isPending
					? "Requesting…"
					: pickerOpen
						? "Confirm request"
						: "Request"}
			</button>
		</div>
	);
}
