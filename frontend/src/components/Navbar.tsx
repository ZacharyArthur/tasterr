import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { User } from "../lib/api";
import { useLogout } from "../lib/auth";
import { useResetRecommendations } from "../lib/taste";

export function Navbar({ user }: { user: User }) {
	const logout = useLogout();
	const reset = useResetRecommendations();
	const [menuOpen, setMenuOpen] = useState(false);
	const menuContainer = useRef<HTMLDivElement>(null);
	const trigger = useRef<HTMLButtonElement>(null);
	useEffect(() => {
		if (!menuOpen) return;
		const dismiss = (event: PointerEvent) => {
			if (!menuContainer.current?.contains(event.target as Node))
				setMenuOpen(false);
		};
		const onKeyDown = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				setMenuOpen(false);
				trigger.current?.focus();
			}
		};
		document.addEventListener("pointerdown", dismiss);
		document.addEventListener("keydown", onKeyDown);
		return () => {
			document.removeEventListener("pointerdown", dismiss);
			document.removeEventListener("keydown", onKeyDown);
		};
	}, [menuOpen]);
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
		<header className="sticky top-0 z-20 flex items-center justify-between gap-4 bg-app-bg/90 px-4 py-3 backdrop-blur sm:px-8">
			<nav className="flex items-center gap-6">
				<Link
					to="/"
					className="text-xl font-bold tracking-tight text-app-text focus-visible:outline-2 focus-visible:outline-app-accent"
				>
					Tasterr
				</Link>
				<Link
					to="/search"
					className="min-h-11 content-center text-sm text-app-subtle transition-colors hover:text-app-text focus-visible:outline-2 focus-visible:outline-app-accent"
				>
					Search
				</Link>
			</nav>
			<div className="flex items-center gap-3 text-sm">
				<div className="relative" ref={menuContainer}>
					<button
						ref={trigger}
						type="button"
						onClick={() => setMenuOpen((value) => !value)}
						aria-haspopup="menu"
						aria-expanded={menuOpen}
						className="min-h-11 text-app-subtle transition-colors hover:text-app-text focus-visible:outline-2 focus-visible:outline-app-accent"
					>
						{user.display_name}
					</button>
					{menuOpen && (
						<div
							role="menu"
							className="absolute right-0 top-full mt-2 w-56 rounded border border-app-border bg-app-panel p-1 shadow-lg"
						>
							{user.is_admin && (
								<Link
									to="/settings"
									role="menuitem"
									onClick={() => setMenuOpen(false)}
									className="block min-h-11 rounded px-3 py-2 text-app-text hover:bg-app-muted focus-visible:outline-2 focus-visible:outline-app-accent"
								>
									Settings
								</Link>
							)}
							<button
								role="menuitem"
								type="button"
								onClick={onReset}
								disabled={reset.isPending}
								className="min-h-11 w-full rounded px-3 py-2 text-left text-app-subtle transition-colors hover:bg-app-muted focus-visible:outline-2 focus-visible:outline-app-accent disabled:opacity-60"
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
					className="min-h-11 rounded border border-app-border px-3 py-1 text-app-subtle transition-colors hover:bg-app-muted focus-visible:outline-2 focus-visible:outline-app-accent disabled:opacity-60"
				>
					Sign out
				</button>
			</div>
			{reset.isSuccess && (
				<output className="sr-only">Recommendations reset.</output>
			)}
			{reset.isError && (
				<span className="sr-only" role="alert">
					Could not reset recommendations.
				</span>
			)}
		</header>
	);
}
