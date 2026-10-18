import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
	ApiError,
	getAccount,
	linkSeerr,
	type SeerrLinkBody,
} from "../lib/api";
import { captureSession, isSessionCurrent } from "../lib/auth";
import { AccountDialog } from "./AccountDialog";

export function ConnectSeerr({
	onConnected,
	onCancel,
}: {
	onConnected: () => void;
	onCancel: () => void;
}) {
	const cache = useQueryClient();
	const account = useQuery({ queryKey: ["account"], queryFn: getAccount });
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const link = useMutation({
		mutationFn: linkSeerr,
		onMutate: () => captureSession(cache),
		onSuccess: async (_data, _body, epoch) => {
			if (!isSessionCurrent(cache, epoch)) return;
			setPassword("");
			await cache.invalidateQueries({ queryKey: ["account"] });
			if (!isSessionCurrent(cache, epoch)) return;
			void cache.invalidateQueries({ queryKey: ["home"] });
		},
	});
	const plex = account.data?.providers.some(
		(provider) =>
			provider.provider === "plex" && provider.linked && provider.available,
	);
	function connect(body: SeerrLinkBody) {
		link.mutate(body, {
			onSuccess: (_data, _body, epoch) => {
				if (epoch !== undefined && isSessionCurrent(cache, epoch))
					onConnected();
			},
		});
	}
	return (
		<AccountDialog title="Connect Seerr" onCancel={onCancel}>
			{plex && (
				<button
					type="button"
					disabled={link.isPending}
					className="min-h-11 rounded bg-app-accent px-4 py-2 text-white"
					onClick={() => connect({ method: "plex" })}
				>
					Use my Plex account
				</button>
			)}
			<form
				className="flex flex-col gap-3"
				onSubmit={(event) => {
					event.preventDefault();
					connect({ method: "local", email, password });
				}}
			>
				<label>
					Email
					<input
						className="min-h-11 w-full rounded border border-app-border bg-app-surface px-3"
						type="email"
						autoComplete="email"
						maxLength={320}
						required
						value={email}
						onChange={(event) => setEmail(event.target.value)}
					/>
				</label>
				<label>
					Password
					<input
						className="min-h-11 w-full rounded border border-app-border bg-app-surface px-3"
						type="password"
						autoComplete="current-password"
						maxLength={4096}
						required
						value={password}
						onChange={(event) => setPassword(event.target.value)}
					/>
				</label>
				<button
					type="submit"
					disabled={link.isPending}
					className="min-h-11 rounded bg-app-accent px-4 py-2 text-white"
				>
					Connect Seerr
				</button>
			</form>
			{link.isError && (
				<p role="alert">
					{link.error instanceof ApiError
						? link.error.message
						: "Could not connect Seerr. Try again."}
				</p>
			)}
		</AccountDialog>
	);
}
