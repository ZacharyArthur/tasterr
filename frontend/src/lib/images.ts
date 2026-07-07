// TMDB image CDN. The host and size slugs are public, stable, well-known values
// (not secrets), so the SPA builds responsive URLs directly from title paths.
const IMAGE_BASE = "https://image.tmdb.org/t/p";

export function posterUrl(
	path: string | null | undefined,
	size: "w185" | "w342" | "w500" = "w342",
): string | null {
	return path ? `${IMAGE_BASE}/${size}${path}` : null;
}

export function backdropUrl(
	path: string | null | undefined,
	size: "w780" | "w1280" | "original" = "w1280",
): string | null {
	return path ? `${IMAGE_BASE}/${size}${path}` : null;
}

export function logoUrl(
	path: string | null | undefined,
	size: "w300" | "w500" = "w500",
): string | null {
	return path ? `${IMAGE_BASE}/${size}${path}` : null;
}

export function profileUrl(path: string | null | undefined): string | null {
	return path ? `${IMAGE_BASE}/w185${path}` : null;
}

export function providerLogoUrl(
	path: string | null | undefined,
): string | null {
	return path ? `${IMAGE_BASE}/w92${path}` : null;
}
