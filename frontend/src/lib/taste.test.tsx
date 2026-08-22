import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { setConfirmedSession } from "./auth";
import { useTasteToggle } from "./taste";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

const USER_B = {
	id: 2,
	display_name: "Viewer B",
	avatar_url: null,
	is_admin: false,
};

function Toggle({ initial }: { initial: boolean }) {
	const toggle = useTasteToggle("movie", 7, "not_interested", initial);
	return (
		<button type="button" onClick={toggle.toggle} disabled={toggle.pending}>
			{toggle.active ? "Hidden" : "Visible"}
		</button>
	);
}

test("a failed prior-session toggle cannot restore its user's state", async () => {
	let rejectSignal!: (reason: Error) => void;
	const signal = new Promise<Response>((_resolve, reject) => {
		rejectSignal = reject;
	});
	const fetchMock = vi.fn(() => signal);
	vi.stubGlobal("fetch", fetchMock);
	const queryClient = new QueryClient({
		defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
	});
	const view = render(
		<QueryClientProvider client={queryClient}>
			<Toggle initial={true} />
		</QueryClientProvider>,
	);

	fireEvent.click(screen.getByRole("button", { name: "Hidden" }));
	await waitFor(() =>
		expect(
			(screen.getByRole("button", { name: "Visible" }) as HTMLButtonElement)
				.disabled,
		).toBe(true),
	);
	await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());

	await setConfirmedSession(queryClient, USER_B);
	view.rerender(
		<QueryClientProvider client={queryClient}>
			<Toggle initial={false} />
		</QueryClientProvider>,
	);
	rejectSignal(new Error("late user-A failure"));
	await new Promise((resolve) => setTimeout(resolve, 0));

	await waitFor(() =>
		expect(
			(screen.getByRole("button", { name: "Visible" }) as HTMLButtonElement)
				.disabled,
		).toBe(false),
	);
	expect(screen.getByRole("button", { name: "Visible" })).toBeTruthy();
});
