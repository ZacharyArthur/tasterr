import { useState } from "react";
import type {
	Availability,
	MediaType,
	RequestDestinationOverride,
} from "../lib/api";
import {
	useConfig,
	useDestinations,
	useRequest,
	variantRequestable,
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
	const missingStandard = variantRequestable(availability, false);
	const missing4k = variantRequestable(availability, true);
	const destinations = useDestinations(
		type,
		id,
		Boolean(config.data?.seerr_configured && (missingStandard || missing4k)),
	);
	const request = useRequest(type, id);
	const [quality, setQuality] = useState<boolean | null>(null);
	const [advancedOpen, setAdvancedOpen] = useState(false);
	const [selection, setSelection] = useState<RequestDestinationOverride | null>(
		null,
	);
	if (!config.data?.seerr_configured) return null;

	const result = request.data;
	if (result?.status === "re_auth_required")
		return (
			<p role="alert" className="text-sm text-status-warning">
				Your Seerr session expired — sign in again to request.
			</p>
		);
	if (result && result.status !== "ok")
		return result.seerr_url ? (
			<a
				href={result.seerr_url}
				target="_blank"
				rel="noreferrer"
				className="inline-flex min-h-11 w-fit items-center rounded bg-app-accent px-3 py-1.5 text-sm font-medium text-white"
			>
				Request in Seerr ↗
			</a>
		) : (
			<p role="alert" className="text-sm text-status-error">
				Couldn’t send the request. Try again later.
			</p>
		);

	const options = destinations.data;
	const submitted = result?.status === "ok";
	const standardAllowed =
		missingStandard &&
		(!options?.available || options.can_request_standard) &&
		!(submitted && !request.variables?.is_4k);
	const fourKAllowed =
		missing4k &&
		Boolean(options?.available && options.can_request_4k) &&
		!(submitted && request.variables?.is_4k);
	if (!standardAllowed && !fourKAllowed)
		return submitted ? (
			<p className="text-sm font-medium text-emerald-400">Requested ✓</p>
		) : null;
	const is4k = quality === null ? !standardAllowed : quality;
	const variantAllowed = is4k ? fourKAllowed : standardAllowed;
	const servers =
		options?.destinations.filter((server) => server.is_4k === is4k) ?? [];
	const active = servers.find(
		(server) => server.server_id === selection?.server_id,
	);
	const validSelection =
		!selection ||
		Boolean(
			active?.quality_profiles.some(
				(profile) => profile.id === selection.profile_id,
			) &&
				active.root_folders.some(
					(folder) => folder.path === selection.root_folder,
				),
		);
	const pending = request.isPending || destinations.isPending;
	const canOverride = Boolean(options?.available && options.can_override);
	const defaultAllowed = !is4k || Boolean(options?.can_request_4k_default);

	function selectServer(value: string) {
		if (value === "default") {
			setSelection(null);
			return;
		}
		const server = servers.find((option) => option.server_id === Number(value));
		if (server)
			setSelection({
				server_id: server.server_id,
				profile_id: server.default_profile_id,
				root_folder: server.default_root_folder,
			});
	}
	function submit() {
		if (
			pending ||
			!variantAllowed ||
			!validSelection ||
			(!selection && !defaultAllowed) ||
			(selection && !canOverride)
		)
			return;
		request.mutate(
			selection
				? { ...selection, ...(is4k ? { is_4k: true } : {}) }
				: is4k
					? { is_4k: true }
					: undefined,
		);
	}
	return (
		<div className="flex flex-col items-start gap-2">
			{submitted && (
				<p className="text-sm font-medium text-emerald-400">Requested ✓</p>
			)}
			{(fourKAllowed || quality !== null) && (
				<label className="flex flex-col gap-1 text-sm">
					<span>Quality</span>
					<select
						value={is4k ? "4k" : "standard"}
						disabled={pending}
						onChange={(event) => {
							setQuality(event.target.value === "4k");
							setSelection(null);
							request.reset();
						}}
						className="min-h-11 rounded border border-app-border bg-app-surface px-2 py-1"
					>
						<option value="standard" disabled={!standardAllowed}>
							Standard
						</option>
						<option value="4k" disabled={!fourKAllowed}>
							4K
						</option>
					</select>
				</label>
			)}
			{!variantAllowed && (
				<p role="alert">
					This version is no longer requestable. Choose another quality.
				</p>
			)}
			{!defaultAllowed && !selection && (
				<p role="alert" className="text-sm text-status-warning">
					No default 4K destination is configured. Choose a destination.
				</p>
			)}
			{request.isError && (
				<p role="alert" className="text-sm text-status-error">
					Couldn’t send the request. Try again or choose a different
					destination.
				</p>
			)}
			{selection && (!validSelection || !canOverride) && (
				<p role="alert" className="text-sm text-status-warning">
					This destination is no longer available. Choose again or use Seerr
					defaults.
				</p>
			)}
			{advancedOpen && (
				<div className="flex flex-col gap-2 text-sm">
					<label className="flex flex-col gap-1">
						<span>Server</span>
						<select
							value={selection?.server_id ?? "default"}
							disabled={pending}
							onChange={(event) => selectServer(event.target.value)}
							className="min-h-11 rounded border border-app-border bg-app-surface px-2 py-1"
						>
							<option value="default" disabled={!defaultAllowed}>
								Use Seerr defaults
							</option>
							{servers.map((server) => (
								<option key={server.server_id} value={server.server_id}>
									{server.server_name}
								</option>
							))}
						</select>
					</label>
					{active && selection && (
						<>
							<label className="flex flex-col gap-1">
								<span>Quality Profile</span>
								<select
									value={selection.profile_id}
									disabled={pending}
									onChange={(event) =>
										setSelection({
											...selection,
											profile_id: Number(event.target.value),
										})
									}
									className="min-h-11 rounded border border-app-border bg-app-surface px-2 py-1"
								>
									{active.quality_profiles.map((profile) => (
										<option key={profile.id} value={profile.id}>
											{profile.name}
										</option>
									))}
								</select>
							</label>
							<label className="flex flex-col gap-1">
								<span>Root Folder</span>
								<select
									value={selection.root_folder}
									disabled={pending}
									onChange={(event) =>
										setSelection({
											...selection,
											root_folder: event.target.value,
										})
									}
									className="min-h-11 rounded border border-app-border bg-app-surface px-2 py-1"
								>
									{active.root_folders.map((folder) => (
										<option key={folder.id} value={folder.path}>
											{folder.path}
										</option>
									))}
								</select>
							</label>
						</>
					)}
					<button
						type="button"
						disabled={request.isPending}
						className="min-h-11 underline"
						onClick={() => {
							setAdvancedOpen(false);
							setSelection(null);
							request.reset();
						}}
					>
						Cancel
					</button>
				</div>
			)}
			{canOverride && servers.length > 0 && !advancedOpen && (
				<button
					type="button"
					disabled={pending}
					className="min-h-11 text-sm underline"
					onClick={() => setAdvancedOpen(true)}
				>
					Choose destination
				</button>
			)}
			<button
				type="button"
				onClick={submit}
				disabled={
					pending ||
					!variantAllowed ||
					!validSelection ||
					(!selection && !defaultAllowed) ||
					Boolean(selection && !canOverride)
				}
				className="min-h-11 w-fit rounded bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-60"
			>
				{request.isPending
					? "Requesting…"
					: destinations.isPending
						? "Loading request options…"
						: advancedOpen
							? "Confirm request"
							: is4k
								? "Request 4K"
								: "Request"}
			</button>
		</div>
	);
}
