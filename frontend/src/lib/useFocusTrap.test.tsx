import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { type ReactNode, StrictMode, useRef } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useFocusTrap } from "./useFocusTrap";

function Trap({
	name,
	onEscape,
	children,
}: {
	name: string;
	onEscape: () => void;
	children?: ReactNode;
}) {
	const ref = useRef<HTMLDivElement>(null);
	useFocusTrap(ref, onEscape);
	return (
		<div ref={ref} role="dialog" aria-label={name} tabIndex={-1}>
			<button type="button">{name} first</button>
			{children}
			<button type="button">{name} last</button>
		</div>
	);
}

let background: HTMLDivElement;
let trigger: HTMLButtonElement;
beforeEach(() => {
	background = document.createElement("div");
	background.id = "shell-background";
	trigger = document.createElement("button");
	background.append(trigger);
	document.body.append(background);
	trigger.focus();
});
afterEach(() => {
	cleanup();
	background.remove();
});

test("same-commit nesting gives inner initial focus, Escape and Tab", () => {
	const outer = vi.fn();
	const inner = vi.fn();
	const view = render(
		<Trap name="outer" onEscape={outer}>
			<Trap name="inner" onEscape={inner} />
		</Trap>,
	);
	expect(document.activeElement).toBe(screen.getByText("inner first"));
	expect(background.inert).toBe(true);
	fireEvent.keyDown(document, { key: "Escape" });
	expect(inner).toHaveBeenCalledOnce();
	expect(outer).not.toHaveBeenCalled();
	screen.getByText("inner last").focus();
	fireEvent.keyDown(document, { key: "Tab" });
	expect(document.activeElement).toBe(screen.getByText("inner first"));
	fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
	expect(document.activeElement).toBe(screen.getByText("inner last"));
	view.unmount();
	expect(document.activeElement).toBe(trigger);
	expect(background.inert).toBe(false);
});

test("outer callback refresh cannot steal focus or Escape; latest callback is used", () => {
	const oldOuter = vi.fn();
	const newOuter = vi.fn();
	const inner = vi.fn();
	const view = render(<Trap name="outer" onEscape={oldOuter} />);
	view.rerender(
		<Trap name="outer" onEscape={oldOuter}>
			<Trap name="inner" onEscape={inner} />
		</Trap>,
	);
	view.rerender(
		<Trap name="outer" onEscape={newOuter}>
			<Trap name="inner" onEscape={inner} />
		</Trap>,
	);
	expect(document.activeElement).toBe(screen.getByText("inner first"));
	fireEvent.keyDown(document, { key: "Escape" });
	expect(inner).toHaveBeenCalledOnce();
	expect(newOuter).not.toHaveBeenCalled();
	view.rerender(<Trap name="outer" onEscape={newOuter} />);
	expect(document.activeElement).toBe(screen.getByText("outer first"));
	fireEvent.keyDown(document, { key: "Escape" });
	expect(newOuter).toHaveBeenCalledOnce();
	expect(oldOuter).not.toHaveBeenCalled();
});

test("removing a lower trap keeps focus in the active trap and preserves its return target", () => {
	const close = vi.fn();
	const view = render(
		<>
			<Trap key="outer" name="outer" onEscape={close} />
			<Trap key="inner" name="inner" onEscape={close} />
		</>,
	);
	const focused = screen.getByText("inner first");
	expect(document.activeElement).toBe(focused);
	view.rerender(<Trap key="inner" name="inner" onEscape={close} />);
	expect(document.activeElement).toBe(focused);
	expect(background.inert).toBe(true);
	view.unmount();
	expect(document.activeElement).toBe(trigger);
	expect(background.inert).toBe(false);
});

test("closing a simultaneously mounted inner trap restores focus within the outer dialog", () => {
	const close = vi.fn();
	const view = render(
		<Trap name="outer" onEscape={close}>
			<Trap name="inner" onEscape={close} />
		</Trap>,
	);
	view.rerender(<Trap name="outer" onEscape={close} />);
	expect(
		screen
			.getByRole("dialog", { name: "outer" })
			.contains(document.activeElement),
	).toBe(true);
	expect(background.inert).toBe(true);
	view.unmount();
	expect(document.activeElement).toBe(trigger);
});

test("StrictMode nesting restores the original trigger after the last trap closes", () => {
	const close = vi.fn();
	const view = render(
		<StrictMode>
			<Trap name="outer" onEscape={close}>
				<Trap name="inner" onEscape={close} />
			</Trap>
		</StrictMode>,
	);
	expect(document.activeElement).toBe(screen.getByText("inner first"));
	view.unmount();
	expect(document.activeElement).toBe(trigger);
	expect(background.inert).toBe(false);
});
