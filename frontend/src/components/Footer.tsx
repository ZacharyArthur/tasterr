import tmdbLogo from "../assets/tmdb.svg";

export function Footer() {
	return (
		<footer className="flex flex-col items-center gap-2 border-t border-app-border px-4 py-6 text-center text-xs text-app-muted-text sm:px-8">
			<a href="https://www.themoviedb.org/" target="_blank" rel="noreferrer">
				<img src={tmdbLogo} alt="TMDB" className="h-4 w-auto" />
			</a>
			<p>
				This product uses the TMDB API but is not endorsed or certified by TMDB.
			</p>
		</footer>
	);
}
