import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router";
import type { MediaDetail, MediaType } from "../lib/api";
import { useTitle } from "../lib/browse";
import {
	backdropUrl,
	logoUrl,
	profileUrl,
	providerLogoUrl,
} from "../lib/images";
import { recordDetailOpen, useExplain, useTasteToggle } from "../lib/taste";
import { useFocusTrap } from "../lib/useFocusTrap";
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
	const titleKey = `${type}:${id}`;
	const previousTitleKey = useRef(titleKey);

	// Opening a detail is deliberate browse intent (SPEC §8) — recorded
	// fire-and-forget so a failed signal never disturbs the view.
	useEffect(() => {
		if (valid) {
			recordDetailOpen(type, id);
		}
	}, [valid, type, id]);
	useEffect(() => {
		const overflow = document.body.style.overflow;
		document.body.style.overflow = "hidden";
		return () => {
			document.body.style.overflow = overflow;
		};
	}, []);

	useFocusTrap(dialogRef, close);
	useEffect(() => {
		if (previousTitleKey.current !== titleKey) {
			previousTitleKey.current = titleKey;
			dialogRef.current?.focus();
		}
	}, [titleKey]);

	return (
		<div className="fixed inset-0 z-30 flex items-start justify-center overflow-y-auto bg-black/70 sm:p-6">
			<div
				ref={dialogRef}
				tabIndex={-1}
				className="relative min-h-full w-full max-w-3xl bg-app-panel text-app-text outline-none sm:min-h-0 sm:rounded-lg"
				role="dialog"
				aria-modal="true"
				aria-label={detail.data?.title ?? "Title details"}
			>
				<button
					type="button"
					onClick={close}
					aria-label="Close"
					className="absolute right-3 top-3 z-10 min-h-11 min-w-11 rounded-full bg-app-bg/80 px-3 py-1 text-app-text hover:bg-app-bg focus-visible:outline-2 focus-visible:outline-app-accent"
				>
					✕
				</button>
				{detail.isPending && <p className="p-8 text-app-subtle">Loading…</p>}
				{detail.isError && (
					<p className="p-8 text-status-error">Could not load this title.</p>
				)}
				{detail.data && (
					// Keyed by title identity: in-modal navigation ("More like this"
					// cards) reuses this component, and the taste-toggle/explainer
					// state must reset per title, never carry over.
					<DetailBody
						key={`${detail.data.media_type}-${detail.data.id}`}
						detail={detail.data}
					/>
				)}
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
			<div className="relative aspect-video w-full overflow-hidden bg-app-bg sm:rounded-t-lg">
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
					<h2 className="text-3xl font-bold text-app-text">{detail.title}</h2>
				)}
				<div className="flex flex-wrap items-center gap-3 text-sm text-app-subtle">
					<AvailabilityBadge availability={detail.availability} />
					{detail.year !== null && <span>{detail.year}</span>}
					{detail.runtime !== null && <span>{detail.runtime} min</span>}
					{detail.certification && (
						<span className="rounded border border-app-border px-1.5 text-xs">
							{detail.certification}
						</span>
					)}
					{detail.genres.length > 0 && (
						<span>{detail.genres.map((genre) => genre.name).join(" · ")}</span>
					)}
				</div>
				{detail.tagline && (
					<p className="italic text-app-subtle">{detail.tagline}</p>
				)}
				<p className="text-app-text">{detail.overview}</p>
				<a
					href={detail.external_url}
					target="_blank"
					rel="noopener noreferrer"
					aria-label="View on TMDB (opens in a new tab)"
					className="min-h-11 self-start text-sm text-app-subtle underline-offset-2 hover:text-app-text hover:underline focus-visible:outline-2 focus-visible:outline-app-accent"
				>
					View on TMDB <span aria-hidden="true">↗</span>
				</a>

				<TasteControls detail={detail} />

				<section className="flex flex-col gap-3">
					<h3 className="text-sm font-semibold text-app-text">
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
									className="flex items-center gap-2 text-sm text-app-subtle"
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
						<h3 className="text-sm font-semibold text-app-text">Cast</h3>
						<ul className="flex gap-4 overflow-x-auto pb-2">
							{cast.map((person) => (
								<li key={person.id} className="w-20 shrink-0 text-center">
									<div className="aspect-square overflow-hidden rounded-full bg-app-muted">
										{profileUrl(person.profile_path) && (
											<img
												src={profileUrl(person.profile_path) ?? undefined}
												alt={person.name}
												className="h-full w-full object-cover"
											/>
										)}
									</div>
									<p className="mt-1 truncate text-xs text-app-text">
										{person.name}
									</p>
									<p className="truncate text-xs text-app-muted-text">
										{person.role}
									</p>
								</li>
							))}
						</ul>
					</section>
				)}

				{detail.seasons.length > 0 && (
					<section className="flex flex-col gap-2">
						<h3 className="text-sm font-semibold text-app-text">Seasons</h3>
						<ul className="flex flex-col gap-1 text-sm text-app-subtle">
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
						<h3 className="text-sm font-semibold text-app-text">
							More like this
						</h3>
						<div className="flex gap-3 overflow-x-auto pb-2">
							{more.map((item) => (
								<MediaCard key={`${item.media_type}-${item.id}`} item={item} />
							))}
						</div>
					</section>
				)}

				<WhyThis type={detail.media_type} id={detail.id} />
			</div>
		</div>
	);
}

function TasteControls({ detail }: { detail: MediaDetail }) {
	const watchlist = useTasteToggle(
		detail.media_type,
		detail.id,
		"watchlist",
		detail.taste?.watchlisted ?? false,
	);
	const hide = useTasteToggle(
		detail.media_type,
		detail.id,
		"not_interested",
		detail.taste?.hidden ?? false,
	);
	return (
		<div className="flex flex-wrap items-center gap-3">
			<button
				type="button"
				onClick={watchlist.toggle}
				disabled={watchlist.pending}
				aria-pressed={watchlist.active}
				className="min-h-11 rounded border border-app-border px-3 py-1 text-sm text-app-text transition-colors hover:bg-app-muted focus-visible:outline-2 focus-visible:outline-app-accent disabled:opacity-60"
			>
				{watchlist.active ? "✓ In My List" : "＋ My List"}
			</button>
			<button
				type="button"
				onClick={hide.toggle}
				disabled={hide.pending}
				aria-pressed={hide.active}
				className="min-h-11 rounded border border-app-border px-3 py-1 text-sm text-app-subtle transition-colors hover:bg-app-muted focus-visible:outline-2 focus-visible:outline-app-accent disabled:opacity-60"
			>
				{hide.active ? "Hidden — undo" : "Not interested"}
			</button>
		</div>
	);
}

function WhyThis({ type, id }: { type: MediaType; id: number }) {
	const [open, setOpen] = useState(false);
	const explain = useExplain(type, id, open);
	return (
		<section className="flex flex-col gap-2">
			<button
				type="button"
				onClick={() => setOpen((value) => !value)}
				aria-expanded={open}
				className="min-h-11 self-start text-sm text-app-subtle underline-offset-2 transition-colors hover:text-app-text hover:underline focus-visible:outline-2 focus-visible:outline-app-accent"
			>
				Why am I seeing this?
			</button>
			{open && explain.isPending && (
				<p className="text-sm text-app-muted-text">Thinking…</p>
			)}
			{open && explain.isError && (
				<p className="text-sm text-app-muted-text">
					Could not load an explanation.
				</p>
			)}
			{open &&
				explain.data &&
				(explain.data.personalized && explain.data.reasons.length > 0 ? (
					<p className="text-sm text-app-text">
						Because you like: {explain.data.reasons.join(", ")}
					</p>
				) : (
					<p className="text-sm text-app-muted-text">
						Not personalized yet — open, request, and save titles you like and
						Tasterr will learn your taste.
					</p>
				))}
		</section>
	);
}
