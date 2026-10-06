import { useRef, useState } from "react";
import type { SeasonSummary } from "../lib/api";
import { useFocusTrap } from "../lib/useFocusTrap";

function Toggle({
	on,
	label,
	detail,
	onChange,
}: {
	on: boolean;
	label: string;
	detail?: string;
	onChange: () => void;
}) {
	return (
		<button
			type="button"
			role="switch"
			aria-checked={on}
			onClick={onChange}
			className="flex min-h-11 w-full items-center gap-3 rounded px-2 text-left text-sm text-app-text hover:bg-app-muted focus-visible:outline-2 focus-visible:outline-app-accent"
		>
			<span
				aria-hidden="true"
				className={`flex h-6 w-11 shrink-0 items-center rounded-full border border-app-border transition-colors ${on ? "bg-app-accent" : "bg-app-surface"}`}
			>
				<span
					className={`size-5 rounded-full bg-white shadow transition-transform ${on ? "translate-x-5" : "translate-x-0.5"}`}
				/>
			</span>
			<span className="flex-1">{label}</span>
			{detail && <span className="text-app-subtle">{detail}</span>}
		</button>
	);
}

/** Season choice for a TV request. Regular seasons start on, Specials off —
 * the same set Seerr's whole-series request covers. */
export function SeasonPicker({
	seasons,
	onConfirm,
	onCancel,
}: {
	seasons: SeasonSummary[];
	onConfirm: (chosen: number[]) => void;
	onCancel: () => void;
}) {
	const dialogRef = useRef<HTMLDivElement>(null);
	const [chosen, setChosen] = useState<ReadonlySet<number>>(
		() =>
			new Set(
				seasons
					.map((season) => season.season_number)
					.filter((number) => number > 0),
			),
	);
	useFocusTrap(dialogRef, onCancel);
	const selected = seasons.filter((season) => chosen.has(season.season_number));
	const all = selected.length === seasons.length;

	function toggle(number: number) {
		const next = new Set(chosen);
		if (!next.delete(number)) next.add(number);
		setChosen(next);
	}
	return (
		<div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4">
			<div
				ref={dialogRef}
				tabIndex={-1}
				role="dialog"
				aria-modal="true"
				aria-labelledby="season-picker-title"
				className="flex max-h-full w-full max-w-md flex-col gap-4 rounded-lg bg-app-panel p-6 text-app-text outline-none"
			>
				<h2 id="season-picker-title" className="text-lg font-semibold">
					Choose seasons
				</h2>
				<div className="border-b border-app-border pb-2">
					<Toggle
						on={all}
						label="All seasons"
						onChange={() =>
							setChosen(
								all
									? new Set()
									: new Set(seasons.map((season) => season.season_number)),
							)
						}
					/>
				</div>
				<div className="-mx-2 flex flex-col gap-1 overflow-y-auto px-2">
					{seasons.map((season) => (
						<Toggle
							key={season.season_number}
							on={chosen.has(season.season_number)}
							label={season.season_number === 0 ? "Specials" : season.name}
							detail={`${season.episode_count} episodes`}
							onChange={() => toggle(season.season_number)}
						/>
					))}
				</div>
				{selected.length === 0 && (
					<p role="alert" className="text-sm text-status-warning">
						Choose at least one season.
					</p>
				)}
				<div className="flex items-center justify-end gap-4">
					<button
						type="button"
						onClick={onCancel}
						className="min-h-11 text-sm underline"
					>
						Cancel
					</button>
					<button
						type="button"
						disabled={selected.length === 0}
						onClick={() =>
							onConfirm(selected.map((season) => season.season_number))
						}
						className="min-h-11 rounded bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-60"
					>
						OK
					</button>
				</div>
			</div>
		</div>
	);
}
