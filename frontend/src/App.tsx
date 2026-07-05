import { useMe } from "./lib/auth";
import { Home } from "./routes/Home";
import { Login } from "./routes/Login";

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
	return <Home user={me.data} />;
}
