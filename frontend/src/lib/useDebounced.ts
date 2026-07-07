import { useEffect, useState } from "react";

/** Returns `value` delayed by `delayMs`; rapid changes collapse to the last one. */
export function useDebounced<T>(value: T, delayMs: number): T {
	const [debounced, setDebounced] = useState(value);
	useEffect(() => {
		const timer = setTimeout(() => setDebounced(value), delayMs);
		return () => clearTimeout(timer);
	}, [value, delayMs]);
	return debounced;
}
