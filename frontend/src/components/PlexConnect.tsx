import { useMutation, useQuery } from "@tanstack/react-query";
import {
	type ReactNode,
	useCallback,
	useEffect,
	useEffectEvent,
	useRef,
	useState,
} from "react";
import {
	ApiError,
	type PinCreateResponse,
	type PinPollResponse,
} from "../lib/api";

export type PlexPoll = Pick<PinPollResponse, "status"> &
	Partial<Pick<PinPollResponse, "user">>;
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
	textarea.style.top = "0";
	textarea.style.left = "0";
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
		try {
			activeElement?.focus();
		} catch {
			// Focus restoration is best effort.
		}
	}
}

export function PlexConnect({
	createPin,
	pollPin,
	onApproved,
	label,
	icon,
	buttonClassName,
	requireUser = false,
}: {
	createPin: () => Promise<PinCreateResponse>;
	pollPin: (pin: string) => Promise<PlexPoll>;
	onApproved: (data: PlexPoll) => void;
	label: string;
	icon?: ReactNode;
	buttonClassName?: string;
	requireUser?: boolean;
}) {
	const approved = useEffectEvent(onApproved);
	const [pin, setPin] = useState<PendingPin | null>(null);
	const [plexError, setPlexError] = useState<string | null>(null);
	const [popupFailed, setPopupFailed] = useState(false);
	const [copyStatus, setCopyStatus] = useState<{
		result: "copied" | "failed";
		attempt: number;
	} | null>(null);
	const approvalWindow = useRef<Window | null>(null);
	const copyAttempt = useRef(0);
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
		const result = (await copyText(authUrl)) ? "copied" : "failed";
		if (source.isConnected) {
			copyAttempt.current += 1;
			setCopyStatus({ result, attempt: copyAttempt.current });
		}
	}

	const startPlex = useMutation({
		mutationFn: createPin,
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
		queryKey: ["auth", "plex-pin", label, pin?.pinId],
		queryFn: () => pollPin(pin?.pinId ?? ""),
		enabled: pin !== null,
		retry: false,
		refetchInterval: (query) =>
			query.state.data?.status === "ok" || query.state.error ? false : 2000,
	});

	const pollData = poll.data;
	const pollError = poll.error;

	useEffect(() => {
		if (pollData?.status === "ok") {
			if (requireUser && pollData.user == null) {
				closeApprovalWindow();
				setCopyStatus(null);
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
			approved(pollData);
			if (!requireUser) setPin(null);
		}
	}, [pollData, closeApprovalWindow, requireUser]);

	useEffect(() => {
		if (pollError !== null) {
			closeApprovalWindow();
			setCopyStatus(null);
			setPlexError(
				pollError instanceof ApiError && pollError.status === 409
					? pollError.message
					: pollError instanceof ApiError && pollError.status === 404
						? "Plex sign-in expired — try again."
						: "Plex sign-in failed — try again.",
			);
			setPin(null);
		}
	}, [pollError, closeApprovalWindow]);

	useEffect(() => closeApprovalWindow, [closeApprovalWindow]);

	return (
		<div className="flex flex-col gap-2" aria-live="polite">
			<button
				type="button"
				onClick={() => {
					openApprovalWindow();
					startPlex.mutate();
				}}
				disabled={startPlex.isPending || pin !== null}
				className={
					buttonClassName ??
					"min-h-11 rounded bg-app-accent px-4 py-2 font-medium text-white transition-colors hover:brightness-110 focus-visible:outline-2 focus-visible:outline-app-text disabled:opacity-60"
				}
			>
				{icon}
				{pin !== null ? "Waiting for Plex approval…" : label}
			</button>
			{pin !== null && (
				<p
					className={`text-sm ${popupFailed ? "text-status-error" : "text-app-subtle"}`}
				>
					{popupFailed
						? "The Plex window isn't available — "
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
					key={copyStatus.attempt}
					className={`text-sm ${copyStatus.result === "failed" ? "text-status-error" : "text-app-subtle"}`}
				>
					{copyStatus.result === "copied"
						? "Approval URL copied."
						: "Could not copy the approval URL. Use the approval link instead."}
				</p>
			)}
			{plexError !== null && (
				<p className="text-sm text-status-error">{plexError}</p>
			)}
		</div>
	);
}
