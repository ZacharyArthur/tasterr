import type { RefObject } from "react";
import { useEffect } from "react";

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
const openTraps: HTMLElement[] = [];

export function useFocusTrap(
	container: RefObject<HTMLElement | null>,
	onEscape: () => void,
): void {
	useEffect(() => {
		const node = container.current;
		if (!node) return;
		const previous = document.activeElement as HTMLElement | null;
		openTraps.push(node);
		const background = document.getElementById("shell-background");
		if (background) background.inert = true;
		const focusable = () =>
			Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
				(element) =>
					!element.hidden && element.getAttribute("aria-hidden") !== "true",
			);
		(focusable()[0] ?? node).focus();
		const onKeyDown = (event: KeyboardEvent) => {
			if (openTraps.at(-1) !== node) return;
			if (event.key === "Escape") {
				event.preventDefault();
				onEscape();
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
			openTraps.splice(openTraps.indexOf(node), 1);
			if (background && openTraps.length === 0) background.inert = false;
			previous?.focus?.();
		};
	}, [container, onEscape]);
}
