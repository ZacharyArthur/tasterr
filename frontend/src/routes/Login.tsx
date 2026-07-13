import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { ApiError, createPlexPin, loginLocal, pollPlexPin } from "../lib/api";
import { ME_QUERY_KEY } from "../lib/auth";

interface PendingPin {
	pinId: string;
	authUrl: string;
}

export function Login() {
	const queryClient = useQueryClient();
	const [pin, setPin] = useState<PendingPin | null>(null);
	const [plexError, setPlexError] = useState<string | null>(null);
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");

	const startPlex = useMutation({
		mutationFn: createPlexPin,
		onSuccess: (created) => {
			setPlexError(null);
			setPin({ pinId: created.pin_id, authUrl: created.auth_url });
			window.open(created.auth_url, "_blank", "noopener");
		},
		onError: () => setPlexError("Could not reach Plex — try again."),
	});

	const poll = useQuery({
		queryKey: ["auth", "plex-pin", pin?.pinId],
		queryFn: () => pollPlexPin(pin?.pinId ?? ""),
		enabled: pin !== null,
		retry: false,
		refetchInterval: (query) =>
			query.state.data?.status === "ok" || query.state.error ? false : 2000,
	});

	const pollData = poll.data;
	const pollError = poll.error;

	useEffect(() => {
		if (pollData?.status === "ok") {
			void queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
		}
	}, [pollData, queryClient]);

	useEffect(() => {
		if (pollError !== null) {
			setPlexError(
				pollError instanceof ApiError && pollError.status === 404
					? "Plex sign-in expired — try again."
					: "Plex sign-in failed — try again.",
			);
			setPin(null);
		}
	}, [pollError]);

	const localLogin = useMutation({
		mutationFn: (credentials: { email: string; password: string }) =>
			loginLocal(credentials.email, credentials.password),
		onSuccess: () =>
			void queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY }),
	});

	function submitLocal(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		localLogin.mutate({ email, password });
	}

	const localError =
		localLogin.error instanceof ApiError && localLogin.error.status === 401
			? localLogin.error.message
			: localLogin.isError
				? "Sign-in failed — try again."
				: null;

	return (
		<main
			data-theme="dark"
			data-accent="crimson"
			className="flex min-h-screen flex-col items-center justify-center gap-8 bg-app-bg px-4 text-app-text"
		>
			<h1 className="text-4xl font-bold tracking-tight">Tasterr</h1>
			<div className="flex w-full max-w-sm flex-col gap-6">
				<div className="flex flex-col gap-2">
					<button
						type="button"
						onClick={() => startPlex.mutate()}
						disabled={startPlex.isPending || pin !== null}
						className="min-h-11 rounded bg-app-accent px-4 py-2 font-medium text-white transition-colors hover:brightness-110 focus-visible:outline-2 focus-visible:outline-app-text disabled:opacity-60"
					>
						{pin !== null ? "Waiting for Plex approval…" : "Sign in with Plex"}
					</button>
					{pin !== null && (
						<p className="text-sm text-app-subtle">
							Approve the sign-in in the Plex window, then come back here.{" "}
							<a
								href={pin.authUrl}
								target="_blank"
								rel="noreferrer"
								className="underline"
							>
								Reopen the approval page
							</a>
						</p>
					)}
					{plexError !== null && (
						<p className="text-sm text-status-error">{plexError}</p>
					)}
				</div>

				<div className="flex items-center gap-3 text-xs uppercase text-app-muted-text">
					<span className="h-px flex-1 bg-app-border" />
					or
					<span className="h-px flex-1 bg-app-border" />
				</div>

				<form onSubmit={submitLocal} className="flex flex-col gap-3">
					<label className="flex flex-col gap-1 text-sm text-app-subtle">
						Email
						<input
							type="email"
							required
							autoComplete="email"
							value={email}
							onChange={(event) => setEmail(event.target.value)}
							className="min-h-11 rounded border border-app-border bg-app-surface px-3 py-2 text-app-text focus-visible:outline-2 focus-visible:outline-app-accent"
						/>
					</label>
					<label className="flex flex-col gap-1 text-sm text-app-subtle">
						Password
						<input
							type="password"
							required
							autoComplete="current-password"
							value={password}
							onChange={(event) => setPassword(event.target.value)}
							className="min-h-11 rounded border border-app-border bg-app-surface px-3 py-2 text-app-text focus-visible:outline-2 focus-visible:outline-app-accent"
						/>
					</label>
					<button
						type="submit"
						disabled={localLogin.isPending}
						className="min-h-11 rounded bg-app-accent px-4 py-2 font-medium text-white transition-colors hover:brightness-110 focus-visible:outline-2 focus-visible:outline-app-text disabled:opacity-60"
					>
						Sign in
					</button>
					{localError !== null && (
						<p className="text-sm text-status-error">{localError}</p>
					)}
				</form>
			</div>
		</main>
	);
}
