import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { PlexConnect } from "../components/PlexConnect";
import {
	ApiError,
	createPlexPin,
	getAuthMethods,
	loginLocal,
	pollPlexPin,
} from "../lib/api";
import { setConfirmedSession } from "../lib/auth";

const pillClassName =
	"relative flex min-h-12 w-full items-center justify-center gap-3 rounded-full border border-app-border bg-app-surface px-12 py-3 font-medium text-app-text transition-colors hover:bg-app-muted focus-visible:outline-2 focus-visible:outline-app-accent disabled:opacity-60";

export function Login() {
	const queryClient = useQueryClient();
	const methods = useQuery({
		queryKey: ["auth", "methods"],
		queryFn: getAuthMethods,
	});
	const [seerrExpanded, setSeerrExpanded] = useState(false);
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
				{methods.data?.plex && (
					<PlexConnect
						createPin={createPlexPin}
						pollPin={pollPlexPin}
						label="Continue with Plex"
						buttonClassName={pillClassName}
						icon={
							<svg
								aria-hidden="true"
								className="absolute left-5 size-6"
								viewBox="0 0 24 24"
							>
								<path fill="#EBAF00" d="M4 0h8l8 12-8 12H4l8-12z" />
							</svg>
						}
						requireUser
						onApproved={(data) => {
							if (data.user) void setConfirmedSession(queryClient, data.user);
						}}
					/>
				)}
				{methods.data?.seerr && (
					<button
						type="button"
						className={pillClassName}
						aria-expanded={seerrExpanded}
						aria-controls="seerr-login"
						onClick={() => setSeerrExpanded(!seerrExpanded)}
					>
						<svg
							aria-hidden="true"
							className="absolute left-5 size-6"
							viewBox="0 0 96 96"
							fill="none"
						>
							<circle cx="52" cy="52" r="28" fill="#131928" />
							<path
								fillRule="evenodd"
								clipRule="evenodd"
								d="M48 96C74.5097 96 96 74.5097 96 48C96 21.4903 74.5097 0 48 0C21.4903 0 0 21.4903 0 48C0 74.5097 21.4903 96 48 96ZM80.0001 52C80.0001 67.464 67.4641 80 52.0001 80C36.5361 80 24.0001 67.464 24.0001 52C24.0001 49.1303 24.4318 46.3615 25.2338 43.7548C27.4288 48.6165 32.3194 52 38.0001 52C45.7321 52 52.0001 45.732 52.0001 38C52.0001 32.3192 48.6166 27.4287 43.755 25.2337C46.3616 24.4317 49.1304 24 52.0001 24C67.4641 24 80.0001 36.536 80.0001 52Z"
								fill="url(#seerr-mark-gradient)"
							/>
							<defs>
								<linearGradient
									id="seerr-mark-gradient"
									x1="48"
									y1="0"
									x2="117.5"
									y2="69.5"
									gradientUnits="userSpaceOnUse"
								>
									<stop stopColor="#C395FC" />
									<stop offset="1" stopColor="#4F65F5" />
								</linearGradient>
							</defs>
						</svg>
						Continue with Seerr
					</button>
				)}
				{methods.isPending && (
					<output className="text-sm text-app-subtle">
						Loading sign-in methods…
					</output>
				)}
				{(methods.isError ||
					(methods.data && !methods.data.plex && !methods.data.seerr)) && (
					<p role="alert" className="text-sm text-status-error">
						Sign-in is currently unavailable.
					</p>
				)}
				{methods.data?.seerr && seerrExpanded && (
					<form
						id="seerr-login"
						onSubmit={submitLocal}
						className="flex flex-col gap-3"
					>
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
				)}
			</div>
		</main>
	);
}
