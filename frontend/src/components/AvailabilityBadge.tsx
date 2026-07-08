import type { Availability } from "../lib/api";

// Only actionable/positive states get a badge. not_requested and unknown (Seerr
// down or unconfigured) render nothing — the card stays clean.
const LABELS: Partial<
	Record<Availability["status"], { label: string; className: string }>
> = {
	available: { label: "Available", className: "bg-emerald-600/90 text-white" },
	partial: { label: "Partial", className: "bg-emerald-700/80 text-white" },
	pending: { label: "Requested", className: "bg-amber-600/90 text-white" },
	processing: { label: "Requested", className: "bg-amber-600/90 text-white" },
};

export function AvailabilityBadge({
	availability,
	className = "",
}: {
	availability?: Availability | null;
	className?: string;
}) {
	if (!availability) {
		return null;
	}
	const meta = LABELS[availability.status];
	if (!meta) {
		return null;
	}
	return (
		<span
			className={`rounded px-1.5 py-0.5 text-xs font-semibold shadow ${meta.className} ${className}`}
		>
			{meta.label}
		</span>
	);
}
