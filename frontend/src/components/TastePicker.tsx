import { useMemo, useState } from "react";
import type { MediaSummary, TasteOnboardingSelection } from "../lib/api";
import { posterUrl } from "../lib/images";
import { useCompleteTasteOnboarding, useTasteOnboarding } from "../lib/taste";

const MAX_SELECTIONS = 12;

export function TastePicker({
	items,
	userId,
}: {
	items: MediaSummary[];
	userId: number | undefined;
}) {
	const status = useTasteOnboarding(userId);
	const complete = useCompleteTasteOnboarding(userId);
	const [selected, setSelected] = useState<
		Map<string, TasteOnboardingSelection>
	>(() => new Map());
	const candidates = useMemo(
		() =>
			Array.from(
				new Map(
					items.map((item) => [`${item.media_type}:${item.id}`, item]),
				).values(),
			).slice(0, MAX_SELECTIONS),
		[items],
	);

	if (status.data?.state !== "show" || candidates.length === 0) {
		return null;
	}

	const toggle = (item: MediaSummary) => {
		const key = `${item.media_type}:${item.id}`;
		setSelected((current) => {
			if (!current.has(key) && current.size >= MAX_SELECTIONS) return current;
			const next = new Map(current);
			if (next.has(key)) next.delete(key);
			else next.set(key, { media_type: item.media_type, tmdb_id: item.id });
			return next;
		});
	};

	return (
		<section
			aria-labelledby="taste-picker-heading"
			className="mx-4 rounded-lg border border-app-border bg-app-panel p-4 sm:mx-8 sm:p-6"
		>
			<h2
				id="taste-picker-heading"
				className="text-xl font-semibold text-app-text"
			>
				Pick a few titles you like
			</h2>
			<p className="mt-1 text-sm text-app-subtle">
				This helps Tasterr tune recommendations. Pick up to 12, or skip and keep
				browsing.
			</p>
			<ul className="mt-4 flex gap-3 overflow-x-auto pb-2">
				{candidates.map((item) => {
					const key = `${item.media_type}:${item.id}`;
					const active = selected.has(key);
					const atLimit = !active && selected.size >= MAX_SELECTIONS;
					const poster = posterUrl(item.poster_path, "w185");
					return (
						<li key={key} className="w-28 shrink-0 sm:w-32">
							<button
								type="button"
								aria-label={`${active ? "Remove" : "Choose"} ${item.title}`}
								aria-pressed={active}
								aria-disabled={atLimit}
								onClick={() => toggle(item)}
								disabled={complete.isPending}
								className={`w-full rounded-md border-2 text-left focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-app-accent disabled:opacity-60 aria-disabled:opacity-60 ${active ? "border-app-accent" : "border-transparent"}`}
							>
								<div className="relative aspect-[2/3] overflow-hidden rounded bg-app-muted">
									{poster ? (
										<img
											src={poster}
											alt=""
											className="h-full w-full object-cover"
										/>
									) : (
										<span className="flex h-full items-center justify-center p-2 text-center text-xs text-app-muted-text">
											{item.title}
										</span>
									)}
									{active && (
										<span
											aria-hidden="true"
											className="absolute right-1 top-1 rounded-full bg-app-accent px-1.5 py-0.5 text-sm text-white"
										>
											{"\u2713"}
										</span>
									)}
								</div>
								<span className="block truncate px-1 py-1 text-sm text-app-text">
									{item.title}
								</span>
							</button>
						</li>
					);
				})}
			</ul>
			<div className="mt-4 flex flex-wrap items-center gap-3">
				<button
					type="button"
					onClick={() => complete.mutate([...selected.values()])}
					disabled={selected.size === 0 || complete.isPending}
					className="min-h-11 rounded bg-app-accent px-4 font-semibold text-white hover:brightness-110 focus-visible:outline-2 focus-visible:outline-app-text disabled:opacity-50"
				>
					Use these picks
				</button>
				<button
					type="button"
					onClick={() => setSelected(new Map())}
					disabled={selected.size === 0 || complete.isPending}
					className="min-h-11 rounded px-4 text-app-subtle hover:bg-app-muted hover:text-app-text focus-visible:outline-2 focus-visible:outline-app-accent disabled:opacity-50"
				>
					Clear picks
				</button>
				<button
					type="button"
					onClick={() => complete.mutate([])}
					disabled={complete.isPending}
					className="min-h-11 rounded px-4 text-app-subtle hover:bg-app-muted hover:text-app-text focus-visible:outline-2 focus-visible:outline-app-accent disabled:opacity-50"
				>
					Skip
				</button>
				{complete.isError && (
					<p role="alert" className="text-sm text-status-error">
						Couldn't save your choices. Try again.
					</p>
				)}
			</div>
		</section>
	);
}
