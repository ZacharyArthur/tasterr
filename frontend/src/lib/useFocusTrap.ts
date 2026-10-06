import type { RefObject } from "react";
import { useEffect, useEffectEvent } from "react";

const FOCUSABLE = [
	"a[href]",
	"button:not([disabled])",
	"input:not([disabled])",
	"select:not([disabled])",
	"textarea:not([disabled])",
	"iframe",
	"[tabindex]:not([tabindex='-1'])",
].join(",");

// Open traps, innermost last: only the top one handles keys, and the page
// behind stays inert until the last one closes.
const openTraps: { node: HTMLElement; previous: HTMLElement | null }[] = [];

export function useFocusTrap(
	container: RefObject<HTMLElement | null>,
	onEscape: () => void,
): void {
	const handleEscape = useEffectEvent(onEscape);
	useEffect(() => {
		const node = container.current;
		if (!node) return;
		const innerIndex = openTraps.findIndex((trap) => node.contains(trap.node));
		const trap = {
			node,
			previous:
				innerIndex < 0
					? (document.activeElement as HTMLElement | null)
					: openTraps[innerIndex].previous,
		};
		openTraps.splice(innerIndex < 0 ? openTraps.length : innerIndex, 0, trap);
		const background = document.getElementById("shell-background");
		if (background) background.inert = true;
		const focusable = () =>
			Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
				(element) =>
					!element.hidden && element.getAttribute("aria-hidden") !== "true",
			);
		if (openTraps.at(-1) === trap) (focusable()[0] ?? node).focus();
		const onKeyDown = (event: KeyboardEvent) => {
			if (openTraps.at(-1) !== trap) return;
			if (event.key === "Escape") {
				event.preventDefault();
				handleEscape();
				return;
			}
			if (event.key !== "Tab") return;
			const items = focusable();
			if (items.length === 0) {
				event.preventDefault();
				node.focus();
				return;
			}
			const first = items[0];
			const last = items.at(-1);
			if (!items.includes(document.activeElement as HTMLElement)) {
				event.preventDefault();
				(event.shiftKey ? last : first)?.focus();
			} else if (event.shiftKey && document.activeElement === first) {
				event.preventDefault();
				last?.focus();
			} else if (!event.shiftKey && document.activeElement === last) {
				event.preventDefault();
				first.focus();
			}
		};
		document.addEventListener("keydown", onKeyDown);
		return () => {
			document.removeEventListener("keydown", onKeyDown);
			const active = openTraps.at(-1) === trap;
			openTraps.splice(openTraps.indexOf(trap), 1);
			for (const remaining of openTraps) {
				if (remaining.previous && node.contains(remaining.previous))
					remaining.previous = trap.previous;
			}
			if (background && openTraps.length === 0) background.inert = false;
			if (!active) return;
			const remaining = openTraps.at(-1)?.node;
			if (
				trap.previous?.isConnected &&
				(!remaining || remaining.contains(trap.previous))
			)
				trap.previous.focus();
			else remaining?.focus();
		};
	}, [container]);
}
