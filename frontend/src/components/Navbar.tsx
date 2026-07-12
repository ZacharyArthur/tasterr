import { useState } from "react";
import { Link } from "react-router-dom";
import type { User } from "../lib/api";
import { useLogout } from "../lib/auth";
import { useResetRecommendations } from "../lib/taste";

export function Navbar({ user }: { user: User }) {
	const logout = useLogout();
	const reset = useResetRecommendations();
	const [menuOpen, setMenuOpen] = useState(false);
	const onReset = () => {
		setMenuOpen(false);
		// An explicit confirm gates the destructive wipe (media-browse spec).
		if (
			window.confirm(
				"Reset your recommendations? This clears everything Tasterr has " +
					"learned and starts over from your Seerr request history.",
			)
		) {
			reset.mutate();
		}
	};
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
				<div className="relative">
					<button
						type="button"
						onClick={() => setMenuOpen((value) => !value)}
						aria-haspopup="menu"
						aria-expanded={menuOpen}
						className="text-neutral-300 transition-colors hover:text-neutral-100"
					>
						{user.display_name}
					</button>
					{menuOpen && (
						<div
							role="menu"
							className="absolute right-0 top-full mt-2 w-56 rounded border border-neutral-800 bg-neutral-950 p-1 shadow-lg"
						>
							<button
								role="menuitem"
								type="button"
								onClick={onReset}
								disabled={reset.isPending}
								className="w-full rounded px-3 py-2 text-left text-neutral-300 transition-colors hover:bg-neutral-900 disabled:opacity-60"
							>
								Reset recommendations
							</button>
						</div>
					)}
				</div>
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
