import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function prefersReduced(): boolean {
	return (
		typeof window !== "undefined" &&
		!!window.matchMedia &&
		window.matchMedia(QUERY).matches
	);
}

/** Tracks the user's reduced-motion preference; JS-driven motion opts out on true. */
export function usePrefersReducedMotion(): boolean {
	const [reduced, setReduced] = useState(prefersReduced);
	useEffect(() => {
		if (!window.matchMedia) {
			return;
		}
		const media = window.matchMedia(QUERY);
		const update = () => setReduced(media.matches);
		update();
		media.addEventListener("change", update);
		return () => media.removeEventListener("change", update);
	}, []);
	return reduced;
}
