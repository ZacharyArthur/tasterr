import { type Location, Route, Routes, useLocation } from "react-router-dom";
import { DetailModal } from "./components/DetailModal";
import { Footer } from "./components/Footer";
import { Navbar } from "./components/Navbar";
import type { User } from "./lib/api";
import { useMe } from "./lib/auth";
import { Home } from "./routes/Home";
import { Login } from "./routes/Login";
import { Search } from "./routes/Search";

export function App() {
	const me = useMe();

	if (me.isPending) {
		return (
			<main className="flex min-h-screen items-center justify-center bg-neutral-950 text-neutral-500">
				Loading…
			</main>
		);
	}
	if (me.isError) {
		return (
			<main className="flex min-h-screen items-center justify-center bg-neutral-950 text-red-400">
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
	const state = location.state as { backgroundLocation?: Location } | null;
	// A card click carries the browse view as backgroundLocation, so the detail
	// modal overlays it; a direct /title/... load falls back to Home behind it.
	return (
		<div className="min-h-screen bg-neutral-950 text-neutral-100">
			<Navbar user={user} />
			<Routes location={state?.backgroundLocation ?? location}>
				<Route path="/" element={<Home />} />
				<Route path="/search" element={<Search />} />
				<Route path="/title/:type/:id" element={<Home />} />
				<Route path="*" element={<Home />} />
			</Routes>
			<Routes>
				<Route path="/title/:type/:id" element={<DetailModal />} />
				<Route path="*" element={null} />
			</Routes>
			<Footer />
		</div>
	);
}
