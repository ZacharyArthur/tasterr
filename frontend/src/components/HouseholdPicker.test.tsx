import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import type { HouseholdMember, MediaSummary, Rail } from "../lib/api";
import { HouseholdPicker } from "./HouseholdPicker";

afterEach(() => {
	cleanup();
	localStorage.clear();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

const member = (id: number, hasTasteSignals = true): HouseholdMember => ({
	id,
	display_name: `Viewer ${id}`,
	avatar_url: null,
	has_taste_signals: hasTasteSignals,
});

const item = (id: number): MediaSummary => ({
	id,
	media_type: "movie",
	title: `Title ${id}`,
	overview: "",
	poster_path: null,
	backdrop_path: null,
	year: 2020,
	vote_average: 7,
});

const blendRail = (...ids: number[]): Rail => ({
	id: "household-blend",
	title: "Something for Everyone Tonight",
	kind: "standard",
	items: ids.map(item),
});

function jsonResponse(body: unknown, status = 200): Response {
	return {
		ok: status >= 200 && status < 300,
		status,
		json: async () => body,
	} as Response;
}

function renderPicker(callerId = 1, queryClient = new QueryClient()) {
	const view = (nextCallerId: number) => (
		<QueryClientProvider client={queryClient}>
			<MemoryRouter>
				<HouseholdPicker key={nextCallerId} callerId={nextCallerId} />
			</MemoryRouter>
		</QueryClientProvider>
	);
	const result = render(view(callerId));
	return {
		...result,
		rerenderCaller: (nextCallerId: number) =>
			result.rerender(view(nextCallerId)),
	};
}

async function openPicker() {
	const heading = await screen.findByRole("heading", {
		name: "Something for Everyone Tonight",
	});
	const details = heading.closest("details");
	expect(details?.open).toBe(false);
	fireEvent.click(heading);
	expect(details?.open).toBe(true);
	return heading;
}

test("starts collapsed and can be opened and hidden", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(async () => jsonResponse([member(1), member(2)])),
	);
	renderPicker();

	const heading = await openPicker();
	expect(
		screen.getByRole("checkbox", { name: "Viewer 1 (you, always included)" }),
	).toBeTruthy();
	fireEvent.click(heading);
	expect(heading.closest("details")?.open).toBe(false);
});

test("locks the caller, enforces the six-person limit, and submits sorted ids", async () => {
	const posts: unknown[] = [];
	vi.stubGlobal(
		"fetch",
		vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
			if (init?.method === "POST") {
				posts.push(JSON.parse(String(init.body)));
				return jsonResponse(null);
			}
			return jsonResponse(
				Array.from({ length: 7 }, (_, index) => member(index + 1)),
			);
		}),
	);
	renderPicker();
	await openPicker();

	const caller = await screen.findByRole("checkbox", {
		name: "Viewer 1 (you, always included)",
	});
	expect((caller as HTMLInputElement).checked).toBe(true);
	expect((caller as HTMLInputElement).disabled).toBe(true);
	const submit = screen.getByRole("button", { name: "Find something for us" });
	expect((submit as HTMLButtonElement).disabled).toBe(true);

	for (const id of [6, 2, 5, 3, 4]) {
		fireEvent.click(screen.getByRole("checkbox", { name: `Viewer ${id}` }));
	}
	const seventh = screen.getByRole("checkbox", { name: "Viewer 7" });
	expect(seventh.getAttribute("aria-disabled")).toBe("true");
	seventh.focus();
	expect(document.activeElement).toBe(seventh);
	fireEvent.click(seventh);
	expect((seventh as HTMLInputElement).checked).toBe(false);

	fireEvent.click(submit);
	await waitFor(() =>
		expect(posts).toEqual([{ user_ids: [1, 2, 3, 4, 5, 6] }]),
	);
	expect((await screen.findByRole("status")).textContent).toContain(
		"No shared picks found",
	);
	expect(localStorage.length).toBe(0);
});

test("renders a standard arrow-navigable rail and hydrates its availability", async () => {
	const requests: string[] = [];
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = String(input);
			requests.push(url);
			if (url.endsWith("household-members")) {
				return jsonResponse([member(1), member(2)]);
			}
			if (url.endsWith("household-blend")) {
				return jsonResponse(blendRail(11, 12, 13, 14));
			}
			const body = JSON.parse(String(init?.body)) as {
				items: { media_type: string; id: number }[];
			};
			return jsonResponse(
				Object.fromEntries(
					body.items.map(({ media_type, id }) => [
						`${media_type}:${id}`,
						{ status: "available", known: true },
					]),
				),
			);
		}),
	);
	const scrollIntoView = vi.fn();
	HTMLElement.prototype.scrollIntoView = scrollIntoView;
	renderPicker();
	const heading = await openPicker();

	fireEvent.click(await screen.findByRole("checkbox", { name: "Viewer 2" }));
	fireEvent.click(
		screen.getByRole("button", { name: "Find something for us" }),
	);

	const cards = await screen.findAllByRole("link");
	expect(cards).toHaveLength(4);
	cards[0].focus();
	fireEvent.keyDown(cards[0], { key: "ArrowRight" });
	expect(document.activeElement).toBe(cards[1]);
	expect(scrollIntoView).toHaveBeenCalled();
	expect(await screen.findAllByText("Available")).toHaveLength(4);
	expect(requests).toContain("/api/v1/availability");

	fireEvent.click(heading);
	expect(heading.closest("details")?.open).toBe(false);
	fireEvent.click(heading);
	expect(screen.getAllByRole("link")).toHaveLength(4);
});

test("omits disabled or ineligible audiences and announces generic failures", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(async () => jsonResponse([member(1), member(2, false)])),
	);
	renderPicker();
	await waitFor(() => expect(fetch).toHaveBeenCalled());
	expect(screen.queryByText("Something for Everyone Tonight")).toBeNull();

	cleanup();
	vi.stubGlobal(
		"fetch",
		vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
			init?.method === "POST"
				? jsonResponse({ detail: "private failure" }, 500)
				: jsonResponse([member(1), member(2)]),
		),
	);
	renderPicker();
	await openPicker();
	fireEvent.click(await screen.findByRole("checkbox", { name: "Viewer 2" }));
	fireEvent.click(
		screen.getByRole("button", { name: "Find something for us" }),
	);
	const alert = await screen.findByRole("alert");
	expect(alert.textContent).toBe("Couldn't find shared picks. Try again.");
	expect(alert.textContent).not.toContain("private failure");
});

test("a confirmed account boundary remount resets selection and results", async () => {
	vi.stubGlobal(
		"fetch",
		vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
			if (init?.method === "POST")
				return jsonResponse(blendRail(21, 22, 23, 24));
			return String(input).endsWith("household-members")
				? jsonResponse([member(1), member(2), member(3)])
				: jsonResponse({});
		}),
	);
	const view = renderPicker(1);
	await openPicker();
	fireEvent.click(await screen.findByRole("checkbox", { name: "Viewer 2" }));
	fireEvent.click(
		screen.getByRole("button", { name: "Find something for us" }),
	);
	expect(await screen.findAllByText("Title 21")).toHaveLength(2);

	view.rerenderCaller(2);
	await openPicker();
	const newCaller = await screen.findByRole("checkbox", {
		name: "Viewer 2 (you, always included)",
	});
	expect((newCaller as HTMLInputElement).checked).toBe(true);
	expect(
		(screen.getByRole("checkbox", { name: "Viewer 1" }) as HTMLInputElement)
			.checked,
	).toBe(false);
	expect(screen.queryByText("Title 21")).toBeNull();
	expect(
		(
			screen.getByRole("button", {
				name: "Find something for us",
			}) as HTMLButtonElement
		).disabled,
	).toBe(true);
});
