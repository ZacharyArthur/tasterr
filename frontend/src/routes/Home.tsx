import { useQuery } from "@tanstack/react-query";
import { getHealth, type User } from "../lib/api";
import { useLogout } from "../lib/auth";

export function Home({ user }: { user: User }) {
	const health = useQuery({ queryKey: ["health"], queryFn: getHealth });
	const logout = useLogout();

	return (
		<main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-neutral-950 text-neutral-100">
			<h1 className="text-4xl font-bold tracking-tight">Tasterr</h1>
			<p className="text-neutral-400">
				Signed in as{" "}
				<span className="font-medium text-neutral-200">
					{user.display_name}
				</span>
			</p>
			{health.isPending && (
				<p className="text-neutral-400">Checking backend…</p>
			)}
			{health.isError && <p className="text-red-400">Backend unreachable</p>}
			{health.isSuccess && (
				<dl className="flex gap-6 text-sm text-neutral-400">
					<div>
						<dt className="font-medium text-neutral-200">Backend</dt>
						<dd>{health.data.status}</dd>
					</div>
					<div>
						<dt className="font-medium text-neutral-200">TMDB</dt>
						<dd>
							{health.data.tmdb_configured ? "configured" : "not configured"}
						</dd>
					</div>
					<div>
						<dt className="font-medium text-neutral-200">Seerr</dt>
						<dd>
							{health.data.seerr_configured ? "configured" : "not configured"}
						</dd>
					</div>
				</dl>
			)}
			<button
				type="button"
				onClick={() => logout.mutate()}
				disabled={logout.isPending}
				className="mt-4 rounded border border-neutral-700 px-4 py-2 text-sm text-neutral-300 transition-colors hover:bg-neutral-900 disabled:opacity-60"
			>
				Sign out
			</button>
		</main>
	);
}
