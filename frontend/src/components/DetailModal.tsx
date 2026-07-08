import { useCallback, useEffect, useRef } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import type { MediaDetail, MediaType } from "../lib/api";
import { useTitle } from "../lib/browse";
import {
	backdropUrl,
	logoUrl,
	profileUrl,
	providerLogoUrl,
} from "../lib/images";
import { AvailabilityBadge } from "./AvailabilityBadge";
import { MediaCard } from "./MediaCard";
import { RequestButton } from "./RequestButton";

function isMediaType(value: string | undefined): value is MediaType {
	return value === "movie" || value === "tv";
}

export function DetailModal() {
	const params = useParams();
	const navigate = useNavigate();
	const location = useLocation();
	// Opened from a card carries the browse view as backgroundLocation → go back
	// to it. A direct /title/... load has no such history → return home instead
	// of navigate(-1) walking the user out of the app.
	const fromCard = Boolean(
		(location.state as { backgroundLocation?: unknown } | null)
			?.backgroundLocation,
	);
	const close = useCallback(() => {
		if (fromCard) {
			navigate(-1);
		} else {
			navigate("/");
		}
	}, [navigate, fromCard]);
	const type = params.type;
	const id = Number(params.id);
	const valid = isMediaType(type) && Number.isFinite(id) && id > 0;
	const detail = useTitle(valid ? type : "movie", valid ? id : 0);
	const dialogRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		const onKeyDown = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				close();
			}
		};
		window.addEventListener("keydown", onKeyDown);
		return () => window.removeEventListener("keydown", onKeyDown);
	}, [close]);

	// Basic focus management: focus the dialog on open, restore on close.
	// (Full focus-trap + inert background is the M5 a11y pass.)
	useEffect(() => {
		const previouslyFocused = document.activeElement as HTMLElement | null;
		dialogRef.current?.focus();
		return () => previouslyFocused?.focus?.();
	}, []);

	return (
		<div className="fixed inset-0 z-30 flex justify-center overflow-y-auto bg-black/70 sm:p-6">
			<div
				ref={dialogRef}
				tabIndex={-1}
				className="relative min-h-full w-full max-w-3xl bg-neutral-900 outline-none sm:min-h-0 sm:rounded-lg"
				role="dialog"
				aria-modal="true"
				aria-label={detail.data?.title ?? "Title details"}
			>
				<button
					type="button"
					onClick={close}
					aria-label="Close"
					className="absolute right-3 top-3 z-10 rounded-full bg-neutral-950/70 px-3 py-1 text-neutral-200 hover:bg-neutral-950"
				>
					✕
				</button>
				{detail.isPending && <p className="p-8 text-neutral-400">Loading…</p>}
				{detail.isError && (
					<p className="p-8 text-red-400">Could not load this title.</p>
				)}
				{detail.data && <DetailBody detail={detail.data} />}
			</div>
		</div>
	);
}

function DetailBody({ detail }: { detail: MediaDetail }) {
	const backdrop = backdropUrl(detail.backdrop_path);
	const logo = logoUrl(detail.logo_path);
	const providers = detail.watch.flatrate;
	const cast = detail.cast.slice(0, 10);
	const more =
		detail.recommendations.length > 0 ? detail.recommendations : detail.similar;
	return (
		<div className="flex flex-col gap-6 pb-8">
			<div className="relative aspect-video w-full overflow-hidden bg-neutral-950 sm:rounded-t-lg">
				{detail.trailer ? (
					<iframe
						title={`${detail.title} trailer`}
						src={`https://www.youtube.com/embed/${detail.trailer.key}`}
						allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
						allowFullScreen
						className="h-full w-full"
					/>
				) : (
					backdrop && (
						<img src={backdrop} alt="" className="h-full w-full object-cover" />
					)
				)}
			</div>
			<div className="flex flex-col gap-4 px-4 sm:px-8">
				{logo ? (
					<img
						src={logo}
						alt={detail.title}
						className="max-h-20 w-auto max-w-xs object-contain object-left"
					/>
				) : (
					<h2 className="text-3xl font-bold text-neutral-50">{detail.title}</h2>
				)}
				<div className="flex flex-wrap items-center gap-3 text-sm text-neutral-400">
					<AvailabilityBadge availability={detail.availability} />
					{detail.year !== null && <span>{detail.year}</span>}
					{detail.runtime !== null && <span>{detail.runtime} min</span>}
					{detail.certification && (
						<span className="rounded border border-neutral-600 px-1.5 text-xs">
							{detail.certification}
						</span>
					)}
					{detail.genres.length > 0 && (
						<span>{detail.genres.map((genre) => genre.name).join(" · ")}</span>
					)}
				</div>
				{detail.tagline && (
					<p className="italic text-neutral-400">{detail.tagline}</p>
				)}
				<p className="text-neutral-300">{detail.overview}</p>

				<section className="flex flex-col gap-3">
					<h3 className="text-sm font-semibold text-neutral-200">
						Where &amp; how to watch
					</h3>
					<RequestButton
						type={detail.media_type}
						id={detail.id}
						availability={detail.availability}
					/>
					{providers.length > 0 && (
						<ul className="flex flex-wrap gap-3">
							{providers.map((provider) => (
								<li
									key={provider.provider_id}
									className="flex items-center gap-2 text-sm text-neutral-400"
								>
									{providerLogoUrl(provider.logo_path) && (
										<img
											src={providerLogoUrl(provider.logo_path) ?? undefined}
											alt=""
											className="h-8 w-8 rounded"
										/>
									)}
									{provider.name}
								</li>
							))}
						</ul>
					)}
				</section>

				{cast.length > 0 && (
					<section className="flex flex-col gap-2">
						<h3 className="text-sm font-semibold text-neutral-200">Cast</h3>
						<ul className="flex gap-4 overflow-x-auto pb-2">
							{cast.map((person) => (
								<li key={person.id} className="w-20 shrink-0 text-center">
									<div className="aspect-square overflow-hidden rounded-full bg-neutral-800">
										{profileUrl(person.profile_path) && (
											<img
												src={profileUrl(person.profile_path) ?? undefined}
												alt={person.name}
												className="h-full w-full object-cover"
											/>
										)}
									</div>
									<p className="mt-1 truncate text-xs text-neutral-300">
										{person.name}
									</p>
									<p className="truncate text-xs text-neutral-500">
										{person.role}
									</p>
								</li>
							))}
						</ul>
					</section>
				)}

				{detail.seasons.length > 0 && (
					<section className="flex flex-col gap-2">
						<h3 className="text-sm font-semibold text-neutral-200">Seasons</h3>
						<ul className="flex flex-col gap-1 text-sm text-neutral-400">
							{detail.seasons.map((season) => (
								<li key={season.season_number}>
									{season.name} — {season.episode_count} episodes
								</li>
							))}
						</ul>
					</section>
				)}

				{more.length > 0 && (
					<section className="flex flex-col gap-2">
						<h3 className="text-sm font-semibold text-neutral-200">
							More like this
						</h3>
						<div className="flex gap-3 overflow-x-auto pb-2">
							{more.map((item) => (
								<MediaCard key={`${item.media_type}-${item.id}`} item={item} />
							))}
						</div>
					</section>
				)}
			</div>
		</div>
	);
}
