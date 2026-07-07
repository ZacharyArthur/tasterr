import type { Rail as RailData } from "../lib/api";
import { MediaCard } from "./MediaCard";

export function Rail({ rail }: { rail: RailData }) {
	return (
		<section className="flex flex-col gap-2">
			<h2 className="px-4 text-lg font-semibold text-neutral-100 sm:px-8">
				{rail.title}
			</h2>
			<div className="flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-2 sm:px-8">
				{rail.items.map((item) => (
					<div key={`${item.media_type}-${item.id}`} className="snap-start">
						<MediaCard item={item} />
					</div>
				))}
			</div>
		</section>
	);
}
