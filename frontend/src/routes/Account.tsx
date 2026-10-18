import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AccountDialog } from "../components/AccountDialog";
import { ConnectSeerr } from "../components/ConnectSeerr";
import { PlexConnect } from "../components/PlexConnect";
import {
	type AccountProvider,
	ApiError,
	createLinkPlexPin,
	deleteAccount,
	getAccount,
	pollLinkPlexPin,
	type User,
	unlinkAccount,
} from "../lib/api";
import {
	captureSession,
	isSessionCurrent,
	setConfirmedSession,
} from "../lib/auth";

export function Account({ user }: { user: User }) {
	const cache = useQueryClient();
	const account = useQuery({ queryKey: ["account"], queryFn: getAccount });
	const [connecting, setConnecting] = useState(false);
	const [unlinking, setUnlinking] = useState<AccountProvider | null>(null);
	const [deleteHistory, setDeleteHistory] = useState(false);
	const [deleting, setDeleting] = useState(false);
	const [confirm, setConfirm] = useState("");
	const refresh = async () => {
		await cache.invalidateQueries({ queryKey: ["account"] });
		void cache.invalidateQueries({ queryKey: ["home"] });
	};
	const unlink = useMutation({
		mutationFn: () =>
			unlinkAccount(unlinking?.provider ?? "plex", deleteHistory),
		onMutate: () => captureSession(cache),
		onSuccess: async (_data, _body, epoch) => {
			if (!isSessionCurrent(cache, epoch)) return;
			setUnlinking(null);
			await refresh();
		},
	});
	const remove = useMutation({
		mutationFn: () => deleteAccount(confirm),
		onMutate: () => captureSession(cache),
		onSuccess: (_data, _body, epoch) => {
			if (isSessionCurrent(cache, epoch))
				return setConfirmedSession(cache, null);
		},
	});
	return (
		<main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-8">
			<h1 className="text-2xl font-semibold">Account</h1>
			<h2 className="text-lg font-semibold">Connected accounts</h2>
			{account.isPending && <p>Loading accounts…</p>}
			{account.isError && <p role="alert">Could not load accounts.</p>}
			{account.data?.providers.map((provider) => (
				<section
					key={provider.provider}
					className="flex flex-col gap-3 rounded border border-app-border bg-app-panel p-4"
				>
					<h3 className="font-semibold">
						{provider.provider === "plex" ? "Plex" : "Seerr"}
					</h3>
					<p>{provider.linked ? provider.display_name : "Not connected"}</p>
					{!provider.available && <p>No longer available on this server</p>}
					{provider.linked ? (
						<>
							<button
								type="button"
								disabled={!provider.can_unlink}
								className="min-h-11 rounded border border-app-border px-4 disabled:opacity-60"
								onClick={() => {
									unlink.reset();
									setDeleteHistory(false);
									setUnlinking(provider);
								}}
							>
								Unlink {provider.provider === "plex" ? "Plex" : "Seerr"}
							</button>
							{!provider.can_unlink && <p>This is your only way to sign in</p>}
						</>
					) : (
						provider.available &&
						(provider.provider === "plex" ? (
							<PlexConnect
								createPin={createLinkPlexPin}
								pollPin={pollLinkPlexPin}
								label="Link Plex"
								onApproved={() => {
									void refresh();
								}}
							/>
						) : (
							<button
								type="button"
								className="min-h-11 rounded bg-app-accent px-4 py-2 text-white"
								onClick={() => setConnecting(true)}
							>
								Link Seerr
							</button>
						))
					)}
				</section>
			))}
			<section className="flex flex-col gap-3 rounded border border-status-error p-4">
				<h2 className="text-lg font-semibold">Danger zone</h2>
				<button
					type="button"
					className="min-h-11 text-status-error underline"
					onClick={() => {
						remove.reset();
						setConfirm("");
						setDeleting(true);
					}}
				>
					Delete my Tasterr account
				</button>
			</section>
			{connecting && (
				<ConnectSeerr
					onCancel={() => setConnecting(false)}
					onConnected={() => setConnecting(false)}
				/>
			)}
			{unlinking && (
				<AccountDialog
					title={`Unlink ${unlinking.provider === "plex" ? "Plex" : "Seerr"}`}
					onCancel={() => setUnlinking(null)}
				>
					<label>
						<input
							type="checkbox"
							checked={deleteHistory}
							onChange={(event) => setDeleteHistory(event.target.checked)}
						/>{" "}
						Also delete history imported from this account
					</label>
					<button
						type="button"
						disabled={unlink.isPending}
						className="min-h-11 rounded bg-app-accent p-2 text-white"
						onClick={() => unlink.mutate()}
					>
						Confirm unlink
					</button>
					{unlink.isError && (
						<p role="alert">
							{unlink.error instanceof ApiError
								? unlink.error.message
								: "Could not unlink account."}
						</p>
					)}
				</AccountDialog>
			)}
			{deleting && (
				<AccountDialog
					title="Delete my Tasterr account"
					onCancel={() => setDeleting(false)}
				>
					<p>
						This permanently deletes your Tasterr data. Nothing is deleted in
						Plex or Seerr.
					</p>
					<label>
						Type {user.display_name} to confirm
						<input
							className="min-h-11 w-full rounded border border-app-border bg-app-surface px-3"
							value={confirm}
							onChange={(event) => setConfirm(event.target.value)}
						/>
					</label>
					<button
						type="button"
						disabled={confirm !== user.display_name || remove.isPending}
						className="min-h-11 rounded bg-app-accent p-2 text-white"
						onClick={() => remove.mutate()}
					>
						Permanently delete account
					</button>
					{remove.isError && <p role="alert">Could not delete your account.</p>}
				</AccountDialog>
			)}
		</main>
	);
}
