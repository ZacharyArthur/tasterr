import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import type { Availability } from "../lib/api";
import { AvailabilityBadge } from "./AvailabilityBadge";

afterEach(cleanup);

function av(status: Availability["status"], known = true): Availability {
	return { status, known };
}

test("labels available and requested states", () => {
	const { rerender } = render(
		<AvailabilityBadge availability={av("available")} />,
	);
	expect(screen.getByText("Available")).toBeTruthy();

	rerender(<AvailabilityBadge availability={av("pending")} />);
	expect(screen.getByText("Requested")).toBeTruthy();

	rerender(<AvailabilityBadge availability={av("processing")} />);
	expect(screen.getByText("Requested")).toBeTruthy();
});

test("renders nothing for not-requested, unknown, or missing status", () => {
	const { container, rerender } = render(
		<AvailabilityBadge availability={av("not_requested")} />,
	);
	expect(container.textContent).toBe("");

	rerender(<AvailabilityBadge availability={av("unknown", false)} />);
	expect(container.textContent).toBe("");

	rerender(<AvailabilityBadge availability={null} />);
	expect(container.textContent).toBe("");
});
