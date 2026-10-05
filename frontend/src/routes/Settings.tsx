import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import {
	MAX_SERVICES,
	RegionServicePicker,
} from "../components/RegionServicePicker";
import {
	useConnectionTest,
	useRegions,
	useSaveSettings,
	useServices,
	useSettings,
} from "../lib/admin";
import {
	ApiError,
	type Appearance,
	type ConnectionTarget,
	type RuntimeSettings,
} from "../lib/api";

const DEFAULT_APPEARANCE: Appearance = { theme: "dark", accent: "crimson" };
const ACCENTS: { id: Appearance["accent"]; label: string }[] = [
	{ id: "crimson", label: "Crimson" },
	{ id: "azure", label: "Azure" },
	{ id: "violet", label: "Violet" },
	{ id: "emerald", label: "Emerald" },
	{ id: "amber", label: "Amber" },
];

export function Settings() {
	const settings = useSettings();
	const regions = useRegions();
	const save = useSaveSettings();
	const probe = useConnectionTest();
	const [draft, setDraft] = useState<RuntimeSettings | null>(null);
	const [saved, setSaved] = useState(false);
	const services = useServices(draft?.region ?? "", draft !== null);

	useEffect(() => {
		if (settings.data) {
			setDraft({
				...settings.data.settings,
				appearance: settings.data.settings.appearance ?? DEFAULT_APPEARANCE,
				hide_library_items: settings.data.settings.hide_library_items ?? false,
				excluded_service_ids: settings.data.settings.excluded_service_ids ?? [],
			});
		}
	}, [settings.data]);

	if (settings.isPending || regions.isPending) {
		return (
			<main className="p-8 text-app-subtle" aria-busy="true">
				Loading settings…
			</main>
		);
	}
	if (settings.error instanceof ApiError && settings.error.status === 403) {
		return (
			<main className="p-8 text-status-error">
				Administrator access required.
			</main>
		);
	}
	if (settings.isError || regions.isError || !draft) {
		return (
			<main className="p-8 text-status-error">Could not load settings.</main>
		);
	}

	const appearance = draft.appearance ?? DEFAULT_APPEARANCE;
	const pending = save.isPending;
	const lockedFields = settings.data.locked_fields ?? [];
	const libraryLocked = lockedFields.includes("hide_library_items");
	const servicesLocked = lockedFields.includes("excluded_service_ids");
	const excludedIds = draft.excluded_service_ids ?? [];
	const exclusionServices = [
		...(services.data?.services ?? []),
		...excludedIds
			.filter(
				(id) =>
					!services.data?.services.some(
						(service) => service.provider_id === id,
					),
			)
			.map((id) => ({
				provider_id: id,
				name: services.isPending
					? `Service ${id} (loading options…)`
					: services.isError
						? `Service ${id} (options unavailable)`
						: `Service ${id} (not in current options)`,
			})),
	];
	const submit = (event: FormEvent) => {
		event.preventDefault();
		setSaved(false);
		save.mutate(draft, { onSuccess: () => setSaved(true) });
	};
	const setAppearance = (next: Partial<Appearance>) =>
		setDraft({ ...draft, appearance: { ...appearance, ...next } });

	return (
		<main className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-8">
			<h1 className="text-3xl font-bold text-app-text">Settings</h1>
			<p className="mt-2 text-app-subtle">
				Household-wide discovery and appearance controls.
			</p>
			<form className="mt-8 flex flex-col gap-8" onSubmit={submit}>
				<SettingsSection title="Catalog">
					<RegionServicePicker
						region={draft.region}
						regions={regions.data.regions}
						services={services.data?.services ?? []}
						selectedIds={draft.service_ids}
						servicesPending={services.isPending}
						servicesError={services.isError}
						disabled={pending}
						onRegionChange={(region) =>
							setDraft({
								...draft,
								region,
								service_ids: [],
								excluded_service_ids: servicesLocked ? excludedIds : [],
							})
						}
						onSelectedIdsChange={(service_ids) =>
							setDraft({ ...draft, service_ids })
						}
					/>
				</SettingsSection>

				<SettingsSection title="Discovery exclusions">
					<p className="mb-4 text-sm text-app-subtle">
						Hide titles from discovery rails, the featured hero, household
						picks, and related suggestions. Search, My List, and Continue
						Watching stay available. Unknown availability stays visible if a
						service is unavailable or verification takes too long.
					</p>
					<label className="flex min-h-11 items-center gap-3 text-app-text">
						<input
							type="checkbox"
							checked={draft.hide_library_items ?? false}
							disabled={pending || libraryLocked}
							onChange={(event) =>
								setDraft({ ...draft, hide_library_items: event.target.checked })
							}
							className="h-5 w-5 accent-app-accent"
						/>
						Hide titles already in the library
					</label>
					<p className="text-sm text-app-subtle">
						Includes partially available TV series and either regular or 4K
						copies.
					</p>
					{libraryLocked && (
						<p className="mt-2 text-sm text-app-subtle">
							Library hiding is controlled by an environment variable.
						</p>
					)}
					<fieldset disabled={pending || servicesLocked} className="mt-6">
						<legend className="font-medium text-app-text">
							Excluded streaming services
						</legend>
						<p className="text-sm text-app-subtle">
							Choose up to {MAX_SERVICES} services. Subscription matches in your
							region are hidden; rental, purchase, free, and ad-supported
							listings alone are kept. Exclusions win over selected streaming
							services, so overlapping choices can leave fewer or empty rails.
						</p>
						{servicesLocked && (
							<p className="mt-2 text-sm text-app-subtle">
								Service exclusions are controlled by an environment variable.
							</p>
						)}
						{excludedIds.length > 0 && (
							<p className="mt-2 text-sm text-app-subtle">
								Excluded:{" "}
								{excludedIds
									.map(
										(id) =>
											services.data?.services.find(
												(service) => service.provider_id === id,
											)?.name ?? `Service ${id}`,
									)
									.join(", ")}
							</p>
						)}
						{services.isPending && (
							<output className="mt-3 block text-sm text-app-subtle">
								Loading exclusion services…
							</output>
						)}
						{services.isError && (
							<p role="alert" className="mt-3 text-sm text-status-error">
								Exclusion services are unavailable. Your current draft is
								unchanged.
							</p>
						)}
						{exclusionServices.length > 0 && (
							<div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
								{exclusionServices.map((service) => {
									const checked = excludedIds.includes(service.provider_id);
									return (
										<label
											key={service.provider_id}
											className="flex min-h-11 items-center gap-3 rounded border border-app-border bg-app-surface px-3 text-sm text-app-text"
										>
											<input
												type="checkbox"
												checked={checked}
												disabled={
													!checked && excludedIds.length >= MAX_SERVICES
												}
												onChange={() =>
													setDraft({
														...draft,
														excluded_service_ids: checked
															? excludedIds.filter(
																	(id) => id !== service.provider_id,
																)
															: [...excludedIds, service.provider_id],
													})
												}
												className="h-5 w-5 accent-app-accent"
											/>
											Exclude {service.name}
										</label>
									);
								})}
							</div>
						)}
						{!servicesLocked && excludedIds.length >= MAX_SERVICES && (
							<output className="mt-2 block text-sm text-status-warning">
								Exclusion limit reached ({MAX_SERVICES} services). Remove one to
								choose another.
							</output>
						)}
					</fieldset>
				</SettingsSection>

				<SettingsSection title="Home rails">
					<div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
						{settings.data.rail_types.map((rail) => {
							const enabled = !draft.disabled_rail_types.includes(rail.id);
							return (
								<label
									key={rail.id}
									className="flex min-h-11 items-center gap-3 rounded border border-app-border bg-app-surface px-3 text-sm text-app-text"
								>
									<input
										type="checkbox"
										checked={enabled}
										disabled={pending}
										onChange={() =>
											setDraft({
												...draft,
												disabled_rail_types: enabled
													? [...draft.disabled_rail_types, rail.id]
													: draft.disabled_rail_types.filter(
															(id) => id !== rail.id,
														),
											})
										}
										className="h-5 w-5 accent-app-accent"
									/>
									{rail.label}
								</label>
							);
						})}
					</div>
				</SettingsSection>

				<SettingsSection title="Appearance">
					<fieldset disabled={pending} className="flex flex-col gap-3">
						<legend className="font-medium text-app-text">Theme</legend>
						<div className="flex gap-4">
							{(["dark", "light"] as const).map((theme) => (
								<label
									key={theme}
									className="flex min-h-11 items-center gap-2 capitalize text-app-text"
								>
									<input
										type="radio"
										name="theme"
										checked={appearance.theme === theme}
										onChange={() => setAppearance({ theme })}
									/>
									{theme}
								</label>
							))}
						</div>
					</fieldset>
					<fieldset disabled={pending} className="mt-4">
						<legend className="font-medium text-app-text">Accent</legend>
						<div className="mt-2 flex flex-wrap gap-2">
							{ACCENTS.map((accent) => (
								<label
									key={accent.id}
									className="flex min-h-11 items-center gap-2 rounded border border-app-border px-3 text-app-text"
								>
									<input
										type="radio"
										name="accent"
										checked={appearance.accent === accent.id}
										onChange={() => setAppearance({ accent: accent.id })}
									/>
									{accent.label}
								</label>
							))}
						</div>
					</fieldset>
				</SettingsSection>

				<SettingsSection title="Connections">
					<p className="text-sm text-app-subtle">
						Tests use the server's configured credentials and never expose them
						here.
					</p>
					<div className="mt-3 flex flex-wrap gap-3">
						{(["tmdb", "seerr"] as ConnectionTarget[]).map((target) => (
							<button
								key={target}
								type="button"
								disabled={probe.isPending || pending}
								onClick={() => probe.mutate(target)}
								className="min-h-11 rounded border border-app-border px-4 font-medium text-app-text hover:bg-app-muted focus-visible:outline-2 focus-visible:outline-app-accent disabled:opacity-60"
							>
								Test {target.toUpperCase()}
							</button>
						))}
					</div>
					{probe.data?.ok && (
						<output className="mt-3 block text-status-success">
							{probe.data.target.toUpperCase()}: {probe.data.detail}
						</output>
					)}
					{probe.data && !probe.data.ok && (
						<p role="alert" className="mt-3 text-status-error">
							{probe.data.target.toUpperCase()}: {probe.data.detail}
						</p>
					)}
					{probe.isError && (
						<p role="alert" className="mt-3 text-status-error">
							Connection test could not run.
						</p>
					)}
				</SettingsSection>

				<div className="sticky bottom-0 flex items-center gap-4 border-t border-app-border bg-app-bg/95 py-4 backdrop-blur">
					<button
						type="submit"
						disabled={pending}
						className="min-h-11 rounded bg-app-accent px-5 font-semibold text-white hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-app-text disabled:opacity-60"
					>
						{pending ? "Saving…" : "Save settings"}
					</button>
					{saved && (
						<output className="text-status-success">Settings saved.</output>
					)}
					{save.isError && (
						<p role="alert" className="text-status-error">
							Could not save settings.
						</p>
					)}
				</div>
			</form>
		</main>
	);
}

function SettingsSection({
	title,
	children,
}: {
	title: string;
	children: ReactNode;
}) {
	return (
		<section className="rounded-lg border border-app-border bg-app-panel p-4 sm:p-6">
			<h2 className="mb-4 text-xl font-semibold text-app-text">{title}</h2>
			{children}
		</section>
	);
}
