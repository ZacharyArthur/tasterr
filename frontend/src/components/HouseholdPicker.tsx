import { useId, useState } from "react";
import type { Rail as RailData } from "../lib/api";
import { AvailabilityContext, useAvailabilityMap } from "../lib/availability";
import { useHouseholdBlend, useHouseholdMembers } from "../lib/household";
import { Rail } from "./Rail";

const MAX_AUDIENCE_SIZE = 6;

export function HouseholdPicker({ callerId }: { callerId: number }) {
	const headingId = useId();
	const members = useHouseholdMembers(callerId);
	const blend = useHouseholdBlend();
	const [selected, setSelected] = useState(() => new Set([callerId]));
	const eligible = (members.data ?? []).filter(
		(member) => member.has_taste_signals,
	);

	if (
		eligible.length < 2 ||
		!eligible.some((member) => member.id === callerId)
	) {
		return null;
	}

	const toggle = (userId: number) => {
		blend.reset();
		setSelected((current) => {
			if (!current.has(userId) && current.size >= MAX_AUDIENCE_SIZE) {
				return current;
			}
			const next = new Set(current);
			if (next.has(userId)) next.delete(userId);
			else next.add(userId);
			return next;
		});
	};

	return (
		<section
			aria-labelledby={headingId}
			className="mx-4 rounded-lg border border-app-border bg-app-panel sm:mx-8"
		>
			<details>
				<summary className="cursor-pointer p-4 focus-visible:outline-2 focus-visible:outline-app-accent sm:p-6">
					<h2 id={headingId} className="text-xl font-semibold text-app-text">
						Something for Everyone Tonight
					</h2>
					<span className="mt-1 block text-sm text-app-subtle">
						Choose who is watching together.
					</span>
				</summary>
				<div className="border-t border-app-border p-4 sm:p-6">
					<p className="text-sm text-app-subtle">
						Your selection stays on this screen only.
					</p>
					<div className="mt-4 flex flex-wrap gap-3">
						{eligible.map((member) => {
							const isCaller = member.id === callerId;
							const checked = selected.has(member.id);
							const atLimit = !checked && selected.size >= MAX_AUDIENCE_SIZE;
							return (
								<label
									key={member.id}
									className={`flex min-h-11 items-center gap-2 rounded border px-3 text-sm text-app-text focus-within:outline-2 focus-within:outline-app-accent ${checked ? "border-app-accent bg-app-muted" : "border-app-border"}`}
								>
									<input
										type="checkbox"
										checked={checked}
										disabled={isCaller || blend.isPending}
										aria-disabled={isCaller || atLimit || blend.isPending}
										onChange={() => {
											if (!atLimit) toggle(member.id);
										}}
										className="size-5 accent-app-accent"
									/>
									<span>
										{member.display_name}
										{isCaller ? " (you, always included)" : ""}
									</span>
								</label>
							);
						})}
					</div>
					<div className="mt-4 flex flex-wrap items-center gap-3">
						<button
							type="button"
							onClick={() =>
								blend.mutate([...selected].sort((left, right) => left - right))
							}
							disabled={selected.size < 2 || blend.isPending}
							className="min-h-11 rounded bg-app-accent px-4 font-semibold text-white hover:brightness-110 focus-visible:outline-2 focus-visible:outline-app-text disabled:opacity-50"
						>
							{blend.isPending
								? "Finding a shared pick…"
								: "Find something for us"}
						</button>
						{blend.isPending && (
							<output className="text-sm text-app-subtle">
								Finding shared picks…
							</output>
						)}
						{blend.isError && (
							<p role="alert" className="text-sm text-status-error">
								Couldn't find shared picks. Try again.
							</p>
						)}
						{blend.isSuccess && blend.data === null && (
							<output className="text-sm text-app-subtle">
								No shared picks found. Try another audience.
							</output>
						)}
					</div>
					{blend.data && <HouseholdRail rail={blend.data} />}
				</div>
			</details>
		</section>
	);
}

function HouseholdRail({ rail }: { rail: RailData }) {
	const availability = useAvailabilityMap(rail.items);
	return (
		<div className="-mx-4 mt-6 sm:-mx-6">
			<AvailabilityContext.Provider value={availability.data ?? {}}>
				<Rail rail={rail} />
			</AvailabilityContext.Provider>
		</div>
	);
}
