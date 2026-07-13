import type { RegionOption, ServiceOption } from "../lib/api";
import { providerLogoUrl } from "../lib/images";

const MAX_SERVICES = 8;

export function RegionServicePicker({
	region,
	regions,
	services,
	selectedIds,
	servicesPending,
	servicesError,
	disabled,
	onRegionChange,
	onSelectedIdsChange,
}: {
	region: string;
	regions: RegionOption[];
	services: ServiceOption[];
	selectedIds: number[];
	servicesPending: boolean;
	servicesError: boolean;
	disabled: boolean;
	onRegionChange: (region: string) => void;
	onSelectedIdsChange: (ids: number[]) => void;
}) {
	const selectedServices = selectedIds
		.map((id) => services.find((service) => service.provider_id === id))
		.filter((service): service is ServiceOption => service !== undefined);
	const toggle = (id: number) => {
		if (selectedIds.includes(id)) {
			onSelectedIdsChange(selectedIds.filter((selected) => selected !== id));
			return;
		}
		if (selectedIds.length < MAX_SERVICES) {
			onSelectedIdsChange([...selectedIds, id]);
		}
	};

	return (
		<div className="flex flex-col gap-4">
			<label className="flex max-w-sm flex-col gap-1 text-sm text-app-subtle">
				Region
				<select
					value={region}
					disabled={disabled}
					onChange={(event) => onRegionChange(event.target.value)}
					className="min-h-11 rounded border border-app-border bg-app-surface px-3 text-app-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-app-accent"
				>
					{regions.map((option) => (
						<option key={option.code} value={option.code}>
							{option.name} ({option.code})
						</option>
					))}
				</select>
			</label>

			<div>
				<h3 className="font-medium text-app-text">Streaming services</h3>
				<p className="text-sm text-app-subtle">
					Choose up to {MAX_SERVICES}. Selection order controls the first
					service rails.
				</p>
				{selectedServices.length > 0 && (
					<p className="mt-2 text-sm text-app-subtle">
						Selected:{" "}
						{selectedServices.map((service) => service.name).join(" → ")}
					</p>
				)}
				{servicesPending && (
					<output className="mt-3 block text-sm text-app-subtle">
						Loading services…
					</output>
				)}
				{servicesError && (
					<p className="mt-3 text-sm text-status-error" role="alert">
						Services are unavailable. Your current draft is unchanged.
					</p>
				)}
				{!servicesPending && !servicesError && (
					<div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
						{services.map((service) => {
							const checked = selectedIds.includes(service.provider_id);
							const atLimit = !checked && selectedIds.length >= MAX_SERVICES;
							const logo = providerLogoUrl(service.logo_path);
							return (
								<label
									key={service.provider_id}
									className="flex min-h-12 items-center gap-3 rounded border border-app-border bg-app-surface px-3 text-sm text-app-text"
								>
									<input
										type="checkbox"
										checked={checked}
										disabled={disabled || atLimit}
										onChange={() => toggle(service.provider_id)}
										className="h-5 w-5 accent-app-accent"
									/>
									{logo && (
										<img src={logo} alt="" className="h-7 w-7 rounded" />
									)}
									<span>{service.name}</span>
								</label>
							);
						})}
					</div>
				)}
				{selectedIds.length >= MAX_SERVICES && (
					<output className="mt-2 block text-sm text-status-warning">
						Eight-service limit reached. Remove one to choose another.
					</output>
				)}
			</div>
		</div>
	);
}
