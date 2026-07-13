import { type KeyboardEvent, useId } from "react";
import type { Rail as RailData } from "../lib/api";
import { MediaCard } from "./MediaCard";

export function Rail({ rail }: { rail: RailData }) {
	const headingId = useId();
	const onKeyDown = (event: KeyboardEvent<HTMLAnchorElement>) => {
		if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
		const current = (event.target as HTMLElement).closest<HTMLElement>(
			"[data-rail-item]",
		);
		if (!current) return;
		const scroller = event.currentTarget.closest("[data-rail-scroller]");
		if (!scroller) return;
		const items = Array.from(
			scroller.querySelectorAll<HTMLElement>("[data-rail-item]"),
		);
		const index = items.indexOf(current);
		const next = items[index + (event.key === "ArrowRight" ? 1 : -1)];
		if (!next) return;
		event.preventDefault();
		next.focus();
		next.scrollIntoView({
			behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
				? "auto"
				: "smooth",
			block: "nearest",
			inline: "nearest",
		});
	};
	return (
		<section className="flex flex-col gap-2" aria-labelledby={headingId}>
			<h2
				id={headingId}
				className="px-4 text-lg font-semibold text-app-text sm:px-8"
			>
				{rail.title}
			</h2>
			<div
				data-rail-scroller
				className="flex snap-x snap-mandatory gap-4 overflow-x-auto px-4 pb-3 sm:px-8"
			>
				{rail.items.map((item) => (
					<div key={`${item.media_type}-${item.id}`} className="snap-start">
						<MediaCard item={item} onKeyDown={onKeyDown} />
					</div>
				))}
			</div>
		</section>
	);
}
