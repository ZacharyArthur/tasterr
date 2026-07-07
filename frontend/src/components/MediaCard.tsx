import { Link, useLocation } from "react-router-dom";
import type { MediaSummary } from "../lib/api";
import { posterUrl } from "../lib/images";

export function MediaCard({ item }: { item: MediaSummary }) {
	const location = useLocation();
	const poster = posterUrl(item.poster_path);
	return (
		<Link
			to={`/title/${item.media_type}/${item.id}`}
			state={{ backgroundLocation: location }}
			className="group block w-32 shrink-0 sm:w-40"
		>
			<div className="aspect-[2/3] overflow-hidden rounded-md bg-neutral-800">
				{poster ? (
					<img
						src={poster}
						alt={item.title}
						loading="lazy"
						className="h-full w-full object-cover motion-safe:transition-transform motion-safe:duration-200 motion-safe:group-hover:scale-105"
					/>
				) : (
					<div className="flex h-full items-center justify-center p-2 text-center text-xs text-neutral-500">
						{item.title}
					</div>
				)}
			</div>
			<p className="mt-1 truncate text-sm text-neutral-300">{item.title}</p>
			{item.year !== null && (
				<p className="text-xs text-neutral-500">{item.year}</p>
			)}
		</Link>
	);
}
