import { vi } from "vitest";

// jsdom implements neither of these; provide inert defaults so components that
// read them render. Individual tests override matchMedia / IntersectionObserver
// when they assert on motion preference or infinite scroll.
if (!window.matchMedia) {
	window.matchMedia = vi.fn((query: string) => ({
		matches: false,
		media: query,
		onchange: null,
		addEventListener: vi.fn(),
		removeEventListener: vi.fn(),
		addListener: vi.fn(),
		removeListener: vi.fn(),
		dispatchEvent: vi.fn(),
	})) as unknown as typeof window.matchMedia;
}

class InertIntersectionObserver {
	root = null;
	rootMargin = "";
	thresholds: readonly number[] = [];
	observe() {}
	unobserve() {}
	disconnect() {}
	takeRecords(): IntersectionObserverEntry[] {
		return [];
	}
}

window.IntersectionObserver =
	InertIntersectionObserver as unknown as typeof window.IntersectionObserver;
