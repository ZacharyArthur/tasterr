import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
	type FormEvent,
	useCallback,
	useEffect,
	useRef,
	useState,
} from "react";
import { ApiError, createPlexPin, loginLocal, pollPlexPin } from "../lib/api";
import { setConfirmedSession } from "../lib/auth";

interface PendingPin {
	pinId: string;
	authUrl: string;
}

const PLEX_POPUP_WIDTH = 600;
const PLEX_POPUP_HEIGHT = 700;

function plexPopupFeatures() {
	const left = Math.round(
		window.screenX + (window.outerWidth - PLEX_POPUP_WIDTH) / 2,
	);
	const top = Math.round(
		window.screenY + (window.outerHeight - PLEX_POPUP_HEIGHT) / 2,
	);
	return `width=${PLEX_POPUP_WIDTH},height=${PLEX_POPUP_HEIGHT},left=${left},top=${top}`;
}

async function copyText(value: string): Promise<boolean> {
	if (navigator.clipboard !== undefined) {
		try {
			await navigator.clipboard.writeText(value);
			return true;
		} catch {
			// Fall back for denied clipboard permissions.
		}
	}

	const activeElement =
		document.activeElement instanceof HTMLElement
			? document.activeElement
			: null;
	const textarea = document.createElement("textarea");
	textarea.value = value;
	textarea.readOnly = true;
	textarea.tabIndex = -1;
	textarea.setAttribute("aria-hidden", "true");
	textarea.style.position = "fixed";
	textarea.style.opacity = "0";
	document.body.append(textarea);
	try {
		textarea.focus();
		textarea.select();
		return document.execCommand("copy");
	} catch {
		return false;
	} finally {
		textarea.remove();
		activeElement?.focus();
	}
}

export function Login() {
	const queryClient = useQueryClient();
	const [pin, setPin] = useState<PendingPin | null>(null);
	const [plexError, setPlexError] = useState<string | null>(null);
	const [popupFailed, setPopupFailed] = useState(false);
	const [copyStatus, setCopyStatus] = useState<"copied" | "failed" | null>(
		null,
	);
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const approvalWindow = useRef<Window | null>(null);
	const closeApprovalWindow = useCallback(() => {
		const approval = approvalWindow.current;
		approvalWindow.current = null;
		try {
			if (approval !== null && !approval.closed) approval.close();
		} catch {
			// Browser opener policies may sever a cross-origin WindowProxy.
		}
	}, []);

	function navigateApprovalWindow(authUrl: string) {
		const approval = approvalWindow.current;
		try {
			if (approval === null) return;
			if (approval.closed) {
				setPopupFailed(true);
				return;
			}
			approval.location.replace(authUrl);
		} catch {
			approvalWindow.current = null;
			setPopupFailed(true);
		}
	}

	function openApprovalWindow() {
		closeApprovalWindow();
		setPopupFailed(false);
		setCopyStatus(null);
		const approval = window.open("", "_blank", plexPopupFeatures());
		if (approval === null) {
			setPopupFailed(true);
			return;
		}
		approvalWindow.current = approval;
		try {
			approval.opener = null;
		} catch {
			closeApprovalWindow();
			setPopupFailed(true);
			return;
		}
		try {
			approval.focus();
		} catch {
			// Focus is progressive enhancement; polling remains authoritative.
		}
	}

	async function copyApprovalUrl(authUrl: string, source: HTMLButtonElement) {
		const status = (await copyText(authUrl)) ? "copied" : "failed";
		if (source.isConnected) setCopyStatus(status);
	}

	const startPlex = useMutation({
		mutationFn: createPlexPin,
		onSuccess: (created) => {
			setPlexError(null);
			setPin({ pinId: created.pin_id, authUrl: created.auth_url });
			navigateApprovalWindow(created.auth_url);
		},
		onError: () => {
			closeApprovalWindow();
			setCopyStatus(null);
			setPlexError("Could not reach Plex — try again.");
		},
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
			if (pollData.user == null) {
				closeApprovalWindow();
				setPlexError("Plex sign-in failed — try again.");
				setPin(null);
				return;
			}
			closeApprovalWindow();
			try {
				window.focus();
			} catch {
				// Browsers may reject programmatic focus after cross-origin navigation.
			}
			void setConfirmedSession(queryClient, pollData.user);
		}
	}, [pollData, queryClient, closeApprovalWindow]);

	useEffect(() => {
		if (pollError !== null) {
			closeApprovalWindow();
			setCopyStatus(null);
			setPlexError(
				pollError instanceof ApiError && pollError.status === 404
					? "Plex sign-in expired — try again."
					: "Plex sign-in failed — try again.",
			);
			setPin(null);
		}
	}, [pollError, closeApprovalWindow]);

	useEffect(() => closeApprovalWindow, [closeApprovalWindow]);

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
				<div className="flex flex-col gap-2" aria-live="polite">
					<button
						type="button"
						onClick={() => {
							openApprovalWindow();
							startPlex.mutate();
						}}
						disabled={startPlex.isPending || pin !== null}
						className="min-h-11 rounded bg-app-accent px-4 py-2 font-medium text-white transition-colors hover:brightness-110 focus-visible:outline-2 focus-visible:outline-app-text disabled:opacity-60"
					>
						{pin !== null ? "Waiting for Plex approval…" : "Sign in with Plex"}
					</button>
					{pin !== null && (
						<p
							className={`text-sm ${popupFailed ? "text-status-error" : "text-app-subtle"}`}
						>
							{popupFailed
								? "We couldn't open the Plex window — "
								: "Approve the sign-in with Plex, then come back here. "}
							<a
								href={pin.authUrl}
								target="_blank"
								rel="noopener noreferrer"
								className="underline"
							>
								{popupFailed ? "open it here" : "Open the approval page"}
							</a>
							.{" "}
							<button
								type="button"
								onClick={(event) =>
									void copyApprovalUrl(pin.authUrl, event.currentTarget)
								}
								className="underline"
							>
								Copy approval URL
							</button>
						</p>
					)}
					{copyStatus !== null && (
						<p
							className={`text-sm ${copyStatus === "failed" ? "text-status-error" : "text-app-subtle"}`}
						>
							{copyStatus === "copied"
								? "Approval URL copied."
								: "Could not copy the approval URL. Use the approval link instead."}
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
