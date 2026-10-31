import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useEffectEvent, useRef, useState } from "react";
import {
	ApiError,
	createTraktDevice,
	pollTraktDevice,
	type TraktDeviceResponse,
} from "../lib/api";
import { captureSession, isSessionCurrent } from "../lib/auth";
import { AccountDialog } from "./AccountDialog";

export function TraktConnect({ onLinked }: { onLinked: () => void }) {
	const cache = useQueryClient();
	const linked = useEffectEvent(onLinked);
	const [open, setOpen] = useState(false);
	const openRef = useRef(false);
	const attempt = useRef(0);
	const [device, setDevice] = useState<TraktDeviceResponse | null>(null);
	const [message, setMessage] = useState<string | null>(null);
	const [restart, setRestart] = useState(false);
	const start = useMutation({
		mutationFn: (_attempt: number) => createTraktDevice(),
		onMutate: () => captureSession(cache),
		onSuccess: (created, started, epoch) => {
			if (
				openRef.current &&
				started === attempt.current &&
				isSessionCurrent(cache, epoch)
			)
				setDevice(created);
		},
		onError: (_error, started, epoch) => {
			if (
				!openRef.current ||
				started !== attempt.current ||
				epoch === undefined ||
				!isSessionCurrent(cache, epoch)
			)
				return;
			setMessage("Could not start the Trakt connection. Try again.");
			setRestart(true);
		},
	});
	function begin() {
		openRef.current = true;
		setOpen(true);
		setDevice(null);
		setMessage(null);
		setRestart(false);
		start.mutate(++attempt.current);
	}
	function cancel() {
		attempt.current += 1;
		openRef.current = false;
		setOpen(false);
		setDevice(null);
	}
	useEffect(() => {
		if (!device) return;
		const epoch = captureSession(cache);
		const handle = device.handle;
		let interval = device.interval;
		let active = true;
		let timer: ReturnType<typeof setTimeout>;
		function stop(text: string) {
			if (!active) return;
			active = false;
			clearTimeout(timer);
			clearTimeout(expiry);
			setMessage(text);
			setRestart(true);
		}
		const expiry = setTimeout(
			() => stop("Trakt authorization expired. Start again."),
			device.expires_in * 1000,
		);
		async function poll() {
			if (!active || !isSessionCurrent(cache, epoch)) return;
			try {
				const result = await pollTraktDevice(handle);
				if (!active || !isSessionCurrent(cache, epoch)) return;
				if (result.status === "linked") {
					active = false;
					openRef.current = false;
					setOpen(false);
					setDevice(null);
					linked();
					return;
				}
				if (result.status === "expired" || result.status === "denied") {
					stop(
						result.status === "expired"
							? "Trakt authorization expired. Start again."
							: "Trakt authorization was denied. If you reached the community-app limit, disconnect an app on Trakt first.",
					);
					return;
				}
				interval = result.interval ?? interval;
				setMessage(null);
			} catch (error) {
				if (!active || !isSessionCurrent(cache, epoch)) return;
				if (
					error instanceof ApiError &&
					(error.status === 404 || error.status === 409)
				) {
					stop(
						error.status === 409
							? error.message
							: "This Trakt connection attempt is no longer available. Start again.",
					);
					return;
				}
				setMessage(
					"Trakt is temporarily unavailable. Still waiting for approval…",
				);
			}
			if (active) timer = setTimeout(() => void poll(), interval * 1000);
		}
		timer = setTimeout(() => void poll(), device.interval * 1000);
		return () => {
			active = false;
			clearTimeout(timer);
			clearTimeout(expiry);
		};
	}, [cache, device]);
	return (
		<>
			<button
				type="button"
				className="min-h-11 rounded bg-app-accent px-4 py-2 text-white"
				onClick={begin}
			>
				Link Trakt
			</button>
			{open && (
				<AccountDialog title="Link Trakt" onCancel={cancel}>
					{start.isPending && <p>Starting Trakt connection…</p>}
					{device && !restart && (
						<>
							<p>Enter this code on Trakt:</p>
							<p className="text-center font-mono text-3xl font-bold tracking-widest">
								{device.user_code}
							</p>
							<a
								className="min-h-11 underline"
								href="https://auth.trakt.tv/activate"
								target="_blank"
								rel="noopener noreferrer"
							>
								Open Trakt activation
							</a>
							<output>Waiting for Trakt approval…</output>
						</>
					)}
					{message && <p role="alert">{message}</p>}
					{restart && (
						<button
							type="button"
							className="min-h-11 underline"
							onClick={begin}
						>
							Start again
						</button>
					)}
				</AccountDialog>
			)}
		</>
	);
}
