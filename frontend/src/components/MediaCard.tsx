import type { KeyboardEventHandler } from "react";
import { Link, type Location, useLocation } from "react-router";
import type { MediaSummary } from "../lib/api";
import { useAvailabilityFor } from "../lib/availability";
import { posterUrl } from "../lib/images";
import { AvailabilityBadge } from "./AvailabilityBadge";

export function MediaCard({
	item,
	onKeyDown,
}: {
	item: MediaSummary;
	onKeyDown?: KeyboardEventHandler<HTMLAnchorElement>;
}) {
	const location = useLocation();
	const poster = posterUrl(item.poster_path);
	const availability = useAvailabilityFor(item);
	const inDetail = location.pathname.startsWith("/title/");
	const backgroundLocation = (
		location.state as { backgroundLocation?: Location } | null
	)?.backgroundLocation;
	return (
		<Link
			data-rail-item
			onKeyDown={onKeyDown}
			to={`/title/${item.media_type}/${item.id}`}
			replace={inDetail}
			state={
				inDetail
					? backgroundLocation && { backgroundLocation }
					: { backgroundLocation: location }
			}
			className="group block w-36 shrink-0 rounded-md focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-app-accent sm:w-44"
		>
			<div className="relative aspect-[2/3] overflow-hidden rounded-md bg-app-muted">
				<AvailabilityBadge
					availability={availability}
					className="absolute left-1 top-1 z-10"
				/>
				{poster ? (
					<img
						src={poster}
						alt={item.title}
						loading="lazy"
						className="h-full w-full object-cover motion-safe:transition-transform motion-safe:duration-200 motion-safe:group-hover:scale-105"
					/>
				) : (
					<div className="flex h-full items-center justify-center p-2 text-center text-xs text-app-muted-text">
						{item.title}
					</div>
				)}
			</div>
			<p className="mt-1 truncate text-sm text-app-text">{item.title}</p>
			{item.year !== null && (
				<p className="text-xs text-app-muted-text">{item.year}</p>
			)}
		</Link>
	);
}
