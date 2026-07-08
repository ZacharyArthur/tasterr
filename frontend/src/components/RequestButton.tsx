import type { Availability, MediaType } from "../lib/api";
import { isRequestable, useConfig, useRequest } from "../lib/availability";

export function RequestButton({
	type,
	id,
	availability,
}: {
	type: MediaType;
	id: number;
	availability?: Availability | null;
}) {
	const config = useConfig();
	const request = useRequest(type, id);

	// Seerr off entirely (or its config not yet known) → no request affordance.
	if (!config.data?.seerr_configured) {
		return null;
	}

	const result = request.data;
	if (result?.status === "re_auth_required") {
		return (
			<p role="alert" className="text-sm text-amber-400">
				Your Seerr session expired — sign in again to request.
			</p>
		);
	}
	if (result && result.status !== "ok") {
		// Seerr down or the request was denied — hand off to Seerr when we can.
		return result.seerr_url ? (
			<a
				href={result.seerr_url}
				target="_blank"
				rel="noreferrer"
				className="inline-flex w-fit items-center gap-1 rounded bg-neutral-700 px-3 py-1.5 text-sm font-medium text-neutral-100 hover:bg-neutral-600"
			>
				Request in Seerr ↗
			</a>
		) : (
			<p className="text-sm text-red-400">
				Couldn’t send the request. Try again later.
			</p>
		);
	}
	if (request.isSuccess) {
		return <p className="text-sm font-medium text-emerald-400">Requested ✓</p>;
	}

	// Already available / requested / status unknown → the badge conveys it; no button.
	if (!isRequestable(availability)) {
		return null;
	}
	return (
		<button
			type="button"
			onClick={() => request.mutate()}
			disabled={request.isPending}
			className="w-fit rounded bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-60"
		>
			{request.isPending ? "Requesting…" : "Request"}
		</button>
	);
}
