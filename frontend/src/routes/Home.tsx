import { useEffect, useRef } from "react";
import { Hero } from "../components/Hero";
import { Rail } from "../components/Rail";
import { useHome, useRails } from "../lib/browse";

export function Home() {
	const home = useHome();
	const rails = useRails();
	const sentinel = useRef<HTMLDivElement>(null);

	const { hasNextPage, isFetchingNextPage, fetchNextPage } = rails;
	useEffect(() => {
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
	}, [hasNextPage, isFetchingNextPage, fetchNextPage]);

	if (home.isPending) {
		return <FeedSkeleton />;
	}
	if (home.isError) {
		return (
			<main className="p-8 text-red-400">Couldn't load your home feed.</main>
		);
	}

	const extraRails = rails.data?.pages.flatMap((page) => page.rails) ?? [];
	return (
		<main className="flex flex-col gap-8 pb-16">
			<Hero slides={home.data.hero} />
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
				<p className="px-4 text-neutral-500 sm:px-8">Loading more…</p>
			)}
		</main>
	);
}

function FeedSkeleton() {
	return (
		<main className="flex flex-col gap-8 pb-16" aria-busy="true">
			<div className="h-[52vh] min-h-80 w-full motion-safe:animate-pulse bg-neutral-900" />
			{[0, 1, 2].map((row) => (
				<div key={row} className="flex flex-col gap-2">
					<div className="mx-4 h-5 w-40 motion-safe:animate-pulse rounded bg-neutral-800 sm:mx-8" />
					<div className="flex gap-3 px-4 sm:px-8">
						{[0, 1, 2, 3, 4, 5].map((card) => (
							<div
								key={card}
								className="aspect-[2/3] w-32 shrink-0 motion-safe:animate-pulse rounded-md bg-neutral-800 sm:w-40"
							/>
						))}
					</div>
				</div>
			))}
		</main>
	);
}
