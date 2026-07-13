import { useContext, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import type { HeroSlide } from "../lib/api";
import { AvailabilityContext, availabilityKey } from "../lib/availability";
import { backdropUrl, logoUrl } from "../lib/images";
import { usePrefersReducedMotion } from "../lib/useReducedMotion";
import { AvailabilityBadge } from "./AvailabilityBadge";

const ROTATE_MS = 7000;

export function Hero({ slides }: { slides: HeroSlide[] }) {
	const location = useLocation();
	const reducedMotion = usePrefersReducedMotion();
	const availabilityMap = useContext(AvailabilityContext);
	const [index, setIndex] = useState(0);
	const count = slides.length;

	useEffect(() => {
		if (reducedMotion || count <= 1) {
			return;
		}
		const timer = setInterval(
			() => setIndex((current) => (current + 1) % count),
			ROTATE_MS,
		);
		return () => clearInterval(timer);
	}, [reducedMotion, count]);

	const slide = slides[index] ?? slides[0];
	if (!slide) {
		return null;
	}
	const backdrop = backdropUrl(slide.item.backdrop_path);
	const logo = logoUrl(slide.logo_path);
	const availability =
		availabilityMap[availabilityKey(slide.item.media_type, slide.item.id)];
	return (
		<section className="relative h-[52vh] min-h-80 w-full overflow-hidden">
			{backdrop && (
				<img
					src={backdrop}
					alt=""
					className="absolute inset-0 h-full w-full object-cover"
				/>
			)}
			<div className="absolute inset-0 bg-gradient-to-t from-app-bg via-app-bg/50 to-transparent" />
			<div className="absolute bottom-0 left-0 flex max-w-2xl flex-col gap-4 p-4 sm:p-8">
				{logo ? (
					<img
						src={logo}
						alt={slide.item.title}
						className="max-h-24 w-auto max-w-xs object-contain object-left"
					/>
				) : (
					<h1 className="text-4xl font-bold text-app-text">
						{slide.item.title}
					</h1>
				)}
				<div className="flex flex-wrap items-center gap-3 text-sm text-app-text">
					<AvailabilityBadge availability={availability} />
					{slide.item.year !== null && <span>{slide.item.year}</span>}
					{slide.certification && (
						<span className="rounded border border-app-border px-1.5 text-xs">
							{slide.certification}
						</span>
					)}
					{slide.genres.length > 0 && <span>{slide.genres.join(" · ")}</span>}
				</div>
				<p className="line-clamp-3 text-sm text-app-text">
					{slide.item.overview}
				</p>
				<Link
					to={`/title/${slide.item.media_type}/${slide.item.id}`}
					state={{ backgroundLocation: location }}
					className="inline-flex min-h-11 w-fit items-center rounded bg-app-accent px-5 py-2 font-medium text-white transition-colors hover:brightness-110 focus-visible:outline-2 focus-visible:outline-app-text"
				>
					View details
				</Link>
			</div>
		</section>
	);
}
