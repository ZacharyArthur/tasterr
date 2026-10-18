import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { PlexConnect } from "../components/PlexConnect";
import { ApiError, createPlexPin, loginLocal, pollPlexPin } from "../lib/api";
import { setConfirmedSession } from "../lib/auth";

export function Login() {
	const queryClient = useQueryClient();
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const localLogin = useMutation({
		mutationFn: (credentials: { email: string; password: string }) =>
			loginLocal(credentials.email, credentials.password),
		onSuccess: (user) => setConfirmedSession(queryClient, user),
	});

	function submitLocal(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		localLogin.mutate({ email, password });
	}

	const localError =
		localLogin.error instanceof ApiError &&
		(localLogin.error.status === 401 || localLogin.error.status === 409)
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
				<PlexConnect
					createPin={createPlexPin}
					pollPin={pollPlexPin}
					label="Sign in with Plex"
					requireUser
					onApproved={(data) => {
						if (data.user) void setConfirmedSession(queryClient, data.user);
					}}
				/>

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
