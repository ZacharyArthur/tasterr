import {
	type Location,
	Navigate,
	Route,
	Routes,
	useLocation,
} from "react-router-dom";
import { DetailModal } from "./components/DetailModal";
import { Footer } from "./components/Footer";
import { Navbar } from "./components/Navbar";
import type { User } from "./lib/api";
import { useMe } from "./lib/auth";
import { useConfig } from "./lib/availability";
import { Home } from "./routes/Home";
import { Login } from "./routes/Login";
import { Search } from "./routes/Search";
import { Settings } from "./routes/Settings";

export function App() {
	const me = useMe();

	if (me.isPending) {
		return (
			<main className="flex min-h-screen items-center justify-center bg-app-bg text-app-muted-text">
				Loading…
			</main>
		);
	}
	if (me.isError) {
		return (
			<main className="flex min-h-screen items-center justify-center bg-app-bg text-status-error">
				Backend unreachable
			</main>
		);
	}
	if (me.data === null) {
		return <Login />;
	}
	return <Shell user={me.data} />;
}

function Shell({ user }: { user: User }) {
	const location = useLocation();
	const config = useConfig();
	const state = location.state as { backgroundLocation?: Location } | null;
	const theme = config.data?.appearance?.theme === "light" ? "light" : "dark";
	const accent = isAccent(config.data?.appearance?.accent)
		? config.data.appearance.accent
		: "crimson";
	// A card click carries the browse view as backgroundLocation, so the detail
	// modal overlays it; a direct /title/... load falls back to Home behind it.
	return (
		<div
			className="min-h-screen bg-app-bg text-app-text"
			data-theme={theme}
			data-accent={accent}
		>
			<div id="shell-background">
				<Navbar user={user} />
				<Routes location={state?.backgroundLocation ?? location}>
					<Route path="/" element={<Home />} />
					<Route path="/search" element={<Search />} />
					<Route
						path="/settings"
						element={user.is_admin ? <Settings /> : <Navigate to="/" replace />}
					/>
					<Route path="/title/:type/:id" element={<Home />} />
					<Route path="*" element={<Home />} />
				</Routes>
				<Footer />
			</div>
			<Routes>
				<Route path="/title/:type/:id" element={<DetailModal />} />
				<Route path="*" element={null} />
			</Routes>
		</div>
	);
}

function isAccent(
	value: string | undefined,
): value is "crimson" | "azure" | "violet" | "emerald" | "amber" {
	return ["crimson", "azure", "violet", "emerald", "amber"].includes(
		value ?? "",
	);
}
