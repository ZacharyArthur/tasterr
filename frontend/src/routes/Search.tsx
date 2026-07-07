import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { MediaCard } from "../components/MediaCard";
import { useSearch } from "../lib/browse";
import { useDebounced } from "../lib/useDebounced";

export function Search() {
	const [params, setParams] = useSearchParams();
	const [text, setText] = useState(() => params.get("q") ?? "");
	const query = useDebounced(text, 300);
	const results = useSearch(query);

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
				className="w-full max-w-xl rounded border border-neutral-700 bg-neutral-900 px-4 py-2 text-neutral-100 placeholder:text-neutral-500"
			/>

			{results.isPending && query.trim() && (
				<p className="text-neutral-400">Searching…</p>
			)}
			{results.isError && (
				<p className="text-red-400">Search failed — try again.</p>
			)}
			{results.data && results.data.results.length === 0 && (
				<p className="text-neutral-400">No results for “{query}”.</p>
			)}
			{results.data && results.data.results.length > 0 && (
				<div className="flex flex-wrap gap-4">
					{results.data.results.map((item) => (
						<MediaCard key={`${item.media_type}-${item.id}`} item={item} />
					))}
				</div>
			)}
		</main>
	);
}
