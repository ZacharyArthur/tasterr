import { type ReactNode, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { useFocusTrap } from "../lib/useFocusTrap";

export function AccountDialog({
	title,
	onCancel,
	children,
}: {
	title: string;
	onCancel: () => void;
	children: ReactNode;
}) {
	const ref = useRef<HTMLDivElement>(null);
	const id = useId();
	useFocusTrap(ref, onCancel);
	return createPortal(
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
			<div
				ref={ref}
				tabIndex={-1}
				role="dialog"
				aria-modal="true"
				aria-labelledby={id}
				className="flex max-h-full w-full max-w-md flex-col gap-4 overflow-y-auto rounded-lg bg-app-panel p-6 text-app-text outline-none"
			>
				<h2 id={id} className="text-lg font-semibold">
					{title}
				</h2>
				{children}
				<button type="button" className="min-h-11 underline" onClick={onCancel}>
					Cancel
				</button>
			</div>
		</div>,
		document.getElementById("shell-background")?.parentElement ?? document.body,
	);
}
