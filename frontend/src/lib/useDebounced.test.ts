import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useDebounced } from "./useDebounced";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test("passes the initial value through immediately", () => {
	const { result } = renderHook(() => useDebounced("a", 300));
	expect(result.current).toBe("a");
});

test("collapses rapid changes to the last value once the delay elapses", () => {
	const { result, rerender } = renderHook(({ v }) => useDebounced(v, 300), {
		initialProps: { v: "a" },
	});

	rerender({ v: "ab" });
	rerender({ v: "abc" });
	expect(result.current).toBe("a"); // nothing emitted before the delay elapses

	act(() => {
		vi.advanceTimersByTime(300);
	});
	expect(result.current).toBe("abc"); // only the final value lands
});
