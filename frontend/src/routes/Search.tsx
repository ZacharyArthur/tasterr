import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { MediaCard } from "../components/MediaCard";
import { AvailabilityContext, useAvailabilityMap } from "../lib/availability";
import { useSearch } from "../lib/browse";
import { useDebounced } from "../lib/useDebounced";

export function Search() {
	const [params, setParams] = useSearchParams();
	const [text, setText] = useState(() => params.get("q") ?? "");
	const query = useDebounced(text, 300);
	const results = useSearch(query);
	const availability = useAvailabilityMap(results.data?.results ?? []);

	// Mirror the debounced query into the URL (shareable/back-button) without
	// pushing a history entry per keystroke.
	useEffect(() => {
		setParams(query ? { q: query } : {}, { replace: true });
	}, [query, setParams]);

	return (
		<main className="flex flex-col gap-6 p-4 sm:p-8">
			<input
				type="search"
				value={text}
				placeholder="Search movies and shows"
				onChange={(event) => setText(event.target.value)}
				className="min-h-11 w-full max-w-xl rounded border border-app-border bg-app-surface px-4 py-2 text-app-text placeholder:text-app-muted-text focus-visible:outline-2 focus-visible:outline-app-accent"
			/>

			{results.isPending && query.trim() && (
				<p className="text-app-subtle">Searching…</p>
			)}
			{results.isError && (
				<p className="text-status-error">Search failed — try again.</p>
			)}
			{results.data && results.data.results.length === 0 && (
				<p className="text-app-subtle">No results for “{query}”.</p>
			)}
			{results.data && results.data.results.length > 0 && (
				<AvailabilityContext.Provider value={availability.data ?? {}}>
					<div className="flex flex-wrap gap-4">
						{results.data.results.map((item) => (
							<MediaCard key={`${item.media_type}-${item.id}`} item={item} />
						))}
					</div>
				</AvailabilityContext.Provider>
			)}
		</main>
	);
}
