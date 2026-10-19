import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { AccountDialog } from "../components/AccountDialog";
import { ConnectSeerr } from "../components/ConnectSeerr";
import { JellyfinCredentialsForm } from "../components/JellyfinCredentialsForm";
import { PlexConnect } from "../components/PlexConnect";
import {
	type AccountProvider,
	type AccountResponse,
	ApiError,
	clearTasteSource,
	createLinkPlexPin,
	deleteAccount,
	getAccount,
	linkJellyfin,
	pollLinkPlexPin,
	setTasteSource,
	type TasteSource,
	type User,
	unlinkAccount,
} from "../lib/api";
import {
	captureSession,
	isSessionCurrent,
	setConfirmedSession,
} from "../lib/auth";

const providerNames = { plex: "Plex", jellyfin: "Jellyfin", seerr: "Seerr" };
const sourceLabels: Record<TasteSource, string> = {
	plex: "Plex history",
	jellyfin: "Jellyfin history",
	seerr: "Seerr request history",
	browsing: "Browsing activity",
};

export function Account({ user }: { user: User }) {
	const cache = useQueryClient();
	const account = useQuery({ queryKey: ["account"], queryFn: getAccount });
	const [connecting, setConnecting] = useState<"seerr" | "jellyfin" | null>(
		null,
	);
	const [unlinking, setUnlinking] = useState<AccountProvider | null>(null);
	const [deleteHistory, setDeleteHistory] = useState(false);
	const [deleting, setDeleting] = useState(false);
	const [confirm, setConfirm] = useState("");
	const [clearing, setClearing] = useState<TasteSource | null>(null);
	const accountsHeading = useRef<HTMLHeadingElement>(null);
	const clearTrigger = useRef<HTMLButtonElement>(null);
	const refreshTaste = () => {
		for (const key of [
			"home",
			"rails",
			"explain",
			"household-members",
			"taste-onboarding",
		]) {
			void cache.invalidateQueries({ queryKey: [key] });
		}
	};
	const refresh = async () => {
		await cache.invalidateQueries({ queryKey: ["account"] });
		void cache.invalidateQueries({ queryKey: ["home"] });
	};
	const jellyfinLink = useMutation({
		mutationFn: linkJellyfin,
		onMutate: () => captureSession(cache),
		onSuccess: async (_data, _body, epoch) => {
			if (!isSessionCurrent(cache, epoch)) return;
			setConnecting(null);
			await refresh();
		},
	});
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
	const toggle = useMutation({
		mutationFn: setTasteSource,
		onMutate: async (body) => {
			const epoch = captureSession(cache);
			await cache.cancelQueries({ queryKey: ["account"] });
			const previous = cache.getQueryData<AccountResponse>(["account"]);
			if (previous && isSessionCurrent(cache, epoch)) {
				cache.setQueryData<AccountResponse>(["account"], {
					...previous,
					taste_sources: {
						...previous.taste_sources,
						[body.source]: body.enabled,
					},
				});
			}
			return { epoch, previous };
		},
		onError: (_error, _body, context) => {
			if (context?.previous && isSessionCurrent(cache, context.epoch)) {
				cache.setQueryData(["account"], context.previous);
			}
		},
		onSuccess: (_data, _body, context) => {
			if (isSessionCurrent(cache, context.epoch)) {
				refreshTaste();
				return cache.invalidateQueries({ queryKey: ["account"] });
			}
		},
	});
	const clear = useMutation({
		mutationFn: clearTasteSource,
		onMutate: () => captureSession(cache),
		onSuccess: async (_data, _source, epoch) => {
			if (!isSessionCurrent(cache, epoch)) return;
			setClearing(null);
			refreshTaste();
			await refresh();
		},
	});
	useEffect(() => {
		if (!clear.isSuccess) return;
		if (clearTrigger.current && !clearTrigger.current.isConnected) {
			accountsHeading.current?.focus();
		}
		clearTrigger.current = null;
	}, [clear.isSuccess]);
	const sourceControls = (source: TasteSource) => (
		<>
			<label className="flex min-h-11 items-center gap-2">
				<input
					type="checkbox"
					role="switch"
					aria-checked={account.data?.taste_sources[source] ?? true}
					checked={account.data?.taste_sources[source] ?? true}
					disabled={toggle.isPending || clear.isPending}
					onChange={(event) =>
						toggle.mutate({ source, enabled: event.target.checked })
					}
				/>
				Use {sourceLabels[source]} for recommendations
			</label>
			<button
				type="button"
				className="min-h-11 text-left underline"
				aria-label={
					source === "browsing"
						? "Clear browsing activity"
						: `Clear imported history from ${providerNames[source]}`
				}
				disabled={clear.isPending || toggle.isPending}
				onClick={(event) => {
					clearTrigger.current = event.currentTarget;
					clear.reset();
					setClearing(source);
				}}
			>
				{source === "browsing"
					? "Clear browsing activity"
					: "Clear imported history"}
			</button>
		</>
	);
	return (
		<main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-8">
			<h1 className="text-2xl font-semibold">Account</h1>
			<h2 ref={accountsHeading} tabIndex={-1} className="text-lg font-semibold">
				Connected accounts
			</h2>
			{account.isPending && <p>Loading accounts…</p>}
			{account.isError && <p role="alert">Could not load accounts.</p>}
			{account.data?.providers.map((provider) => (
				<section
					key={provider.provider}
					className="flex flex-col gap-3 rounded border border-app-border bg-app-panel p-4"
				>
					<h3 className="font-semibold">{providerNames[provider.provider]}</h3>
					{(provider.linked || provider.available) && (
						<p>{provider.linked ? provider.display_name : "Not connected"}</p>
					)}
					{!provider.available && provider.linked && (
						<p>No longer available on this server</p>
					)}
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
								Unlink {providerNames[provider.provider]}
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
								onClick={() => {
									jellyfinLink.reset();
									setConnecting(
										provider.provider === "jellyfin" ? "jellyfin" : "seerr",
									);
								}}
							>
								Link {providerNames[provider.provider]}
							</button>
						))
					)}
					{sourceControls(provider.provider)}
				</section>
			))}
			{account.data && (
				<section className="flex flex-col gap-3 rounded border border-app-border bg-app-panel p-4">
					<h2 className="text-lg font-semibold">Browsing activity</h2>
					{sourceControls("browsing")}
				</section>
			)}
			{toggle.isError && (
				<p role="alert">Could not update taste source. Try again.</p>
			)}
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
			{connecting === "seerr" && (
				<ConnectSeerr
					onCancel={() => setConnecting(null)}
					onConnected={() => setConnecting(null)}
				/>
			)}
			{connecting === "jellyfin" && (
				<AccountDialog
					title="Link Jellyfin"
					onCancel={() => setConnecting(null)}
				>
					<JellyfinCredentialsForm
						onSubmit={(body) => jellyfinLink.mutate(body)}
						pending={jellyfinLink.isPending}
						submitLabel="Connect Jellyfin"
					/>
					{jellyfinLink.isError && (
						<p role="alert">
							{jellyfinLink.error instanceof ApiError
								? jellyfinLink.error.message
								: "Could not connect Jellyfin. Try again."}
						</p>
					)}
				</AccountDialog>
			)}
			{unlinking && (
				<AccountDialog
					title={`Unlink ${providerNames[unlinking.provider]}`}
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
						Plex, Jellyfin, or Seerr.
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
			{clearing && (
				<AccountDialog
					title={`Clear ${sourceLabels[clearing]}`}
					onCancel={() => setClearing(null)}
				>
					<p>
						{clearing === "browsing"
							? "Delete stored browsing activity?"
							: "Delete history imported from this account?"}{" "}
						Your source setting stays the same.
					</p>
					{clearing !== "browsing" && (
						<p>
							Recent activity may return on the next sync. If this source has
							never finished syncing, its full history window may return. Switch
							it off to stop importing.
						</p>
					)}
					<button
						type="button"
						disabled={clear.isPending}
						className="min-h-11 rounded bg-app-accent p-2 text-white"
						onClick={() => clear.mutate(clearing)}
					>
						Confirm clear
					</button>
					{clear.isError && (
						<p role="alert">Could not clear history. Try again.</p>
					)}
				</AccountDialog>
			)}
		</main>
	);
}
