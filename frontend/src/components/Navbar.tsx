import { Link } from "react-router-dom";
import type { User } from "../lib/api";
import { useLogout } from "../lib/auth";

export function Navbar({ user }: { user: User }) {
	const logout = useLogout();
	return (
		<header className="sticky top-0 z-20 flex items-center justify-between gap-4 bg-neutral-950/80 px-4 py-3 backdrop-blur sm:px-8">
			<nav className="flex items-center gap-6">
				<Link
					to="/"
					className="text-xl font-bold tracking-tight text-neutral-50"
				>
					Tasterr
				</Link>
				<Link
					to="/search"
					className="text-sm text-neutral-400 transition-colors hover:text-neutral-100"
				>
					Search
				</Link>
			</nav>
			<div className="flex items-center gap-3 text-sm">
				<span className="text-neutral-300">{user.display_name}</span>
				<button
					type="button"
					onClick={() => logout.mutate()}
					disabled={logout.isPending}
					className="rounded border border-neutral-700 px-3 py-1 text-neutral-300 transition-colors hover:bg-neutral-900 disabled:opacity-60"
				>
					Sign out
				</button>
			</div>
		</header>
	);
}
