import { useState } from "react";
import type { JellyfinCredentials } from "../lib/api";

export function JellyfinCredentialsForm({
	onSubmit,
	pending,
	submitLabel,
}: {
	onSubmit: (body: JellyfinCredentials) => void;
	pending: boolean;
	submitLabel: string;
}) {
	const [username, setUsername] = useState("");
	const [password, setPassword] = useState("");
	return (
		<form
			aria-label="Jellyfin credentials"
			className="flex flex-col gap-3"
			onSubmit={(event) => {
				event.preventDefault();
				onSubmit({ username, password });
			}}
		>
			<label className="flex flex-col gap-1 text-sm text-app-subtle">
				Username
				<input
					autoComplete="username"
					required
					maxLength={320}
					value={username}
					onChange={(event) => setUsername(event.target.value)}
					className="min-h-11 rounded border border-app-border bg-app-surface px-3 py-2 text-app-text focus-visible:outline-2 focus-visible:outline-app-accent"
				/>
			</label>
			<label className="flex flex-col gap-1 text-sm text-app-subtle">
				Password
				<input
					type="password"
					autoComplete="current-password"
					maxLength={4096}
					value={password}
					onChange={(event) => setPassword(event.target.value)}
					className="min-h-11 rounded border border-app-border bg-app-surface px-3 py-2 text-app-text focus-visible:outline-2 focus-visible:outline-app-accent"
				/>
			</label>
			<button
				type="submit"
				disabled={pending}
				className="min-h-11 rounded bg-app-accent px-4 py-2 font-medium text-white focus-visible:outline-2 focus-visible:outline-app-text disabled:opacity-60"
			>
				{submitLabel}
			</button>
		</form>
	);
}
