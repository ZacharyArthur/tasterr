import { useEffect, useRef } from "react";
import { Link } from "react-router";
import { Hero } from "../components/Hero";
import { Rail } from "../components/Rail";
import { TastePicker } from "../components/TastePicker";
import type { MediaSummary } from "../lib/api";
import { useMe } from "../lib/auth";
import { AvailabilityContext, useAvailabilityMap } from "../lib/availability";
import { useHome, useRails } from "../lib/browse";

export function Home() {
	const home = useHome();
	const rails = useRails();
	const me = useMe();
	const sentinel = useRef<HTMLDivElement>(null);

	const { hasNextPage, isFetchingNextPage, fetchNextPage } = rails;
	useEffect(() => {
		if (home.isPending) {
			return;
		}
		const node = sentinel.current;
		if (!node) {
			return;
		}
		const observer = new IntersectionObserver(
			(entries) => {
				if (entries[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) {
					void fetchNextPage();
				}
			},
			{ rootMargin: "600px" },
		);
		observer.observe(node);
		return () => observer.disconnect();
	}, [home.isPending, hasNextPage, isFetchingNextPage, fetchNextPage]);

	// Every title on screen, batch-hydrated after the feed paints (never blocking
	// the initial render). Grows as infinite scroll loads more rails.
	const extraRails = rails.data?.pages.flatMap((page) => page.rails) ?? [];
	const items: MediaSummary[] = [
		...(home.data?.hero.map((slide) => slide.item) ?? []),
		...(home.data?.rails.flatMap((rail) => rail.items) ?? []),
		...extraRails.flatMap((rail) => rail.items),
	];
	const availability = useAvailabilityMap(items);

	if (home.isPending) {
		return <FeedSkeleton />;
	}
	if (home.isError) {
		return (
			<main className="p-8 text-status-error">
				Couldn't load your home feed.
			</main>
		);
	}
	const empty =
		home.data.hero.length === 0 &&
		home.data.rails.length === 0 &&
		extraRails.length === 0;

	return (
		<AvailabilityContext.Provider value={availability.data ?? {}}>
			<main className="flex flex-col gap-8 pb-16">
				{empty && (
					<section className="mx-auto my-20 max-w-xl px-6 text-center">
						<h1 className="text-2xl font-semibold text-app-text">
							Your home feed is empty
						</h1>
						<p className="mt-2 text-app-subtle">
							An administrator may have disabled every home rail.
						</p>
						{me.data?.is_admin && (
							<Link
								to="/settings"
								className="mt-5 inline-flex min-h-11 items-center rounded bg-app-accent px-4 font-medium text-white focus-visible:outline-2 focus-visible:outline-app-text"
							>
								Open Settings
							</Link>
						)}
					</section>
				)}
				<Hero slides={home.data.hero} />
				<TastePicker items={items} userId={me.data?.id} />
				<div className="flex flex-col gap-8">
					{home.data.rails.map((rail) => (
						<Rail key={rail.id} rail={rail} />
					))}
					{extraRails.map((rail) => (
						<Rail key={rail.id} rail={rail} />
					))}
				</div>
				<div ref={sentinel} className="h-4" />
				{isFetchingNextPage && (
					<p className="px-4 text-app-muted-text sm:px-8">Loading more…</p>
				)}
			</main>
		</AvailabilityContext.Provider>
	);
}

function FeedSkeleton() {
	return (
		<main className="flex flex-col gap-8 pb-16" aria-busy="true">
			<div className="h-[52vh] min-h-80 w-full motion-safe:animate-pulse bg-app-surface" />
			{[0, 1, 2].map((row) => (
				<div key={row} className="flex flex-col gap-2">
					<div className="mx-4 h-5 w-40 motion-safe:animate-pulse rounded bg-app-muted sm:mx-8" />
					<div className="flex gap-3 px-4 sm:px-8">
						{[0, 1, 2, 3, 4, 5].map((card) => (
							<div
								key={card}
								className="aspect-[2/3] w-36 shrink-0 motion-safe:animate-pulse rounded-md bg-app-muted sm:w-44"
							/>
						))}
					</div>
				</div>
			))}
		</main>
	);
}
