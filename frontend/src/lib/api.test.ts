import { afterEach, expect, test, vi } from "vitest";
import {
	ApiError,
	getMe,
	getServices,
	loginLocal,
	logout,
	saveSettings,
	testConnection,
} from "./api";

afterEach(() => {
	vi.unstubAllGlobals();
});

function stubFetch(status: number, body?: unknown) {
	const mock = vi.fn(async () => {
		return {
			ok: status >= 200 && status < 300,
			status,
			json: async () => {
				if (body === undefined) {
					throw new Error("no body");
				}
				return body;
			},
		} as Response;
	});
	vi.stubGlobal("fetch", mock);
	return mock;
}

test("getMe returns the user when authenticated", async () => {
	stubFetch(200, {
		id: 1,
		display_name: "Viewer",
		avatar_url: null,
		is_admin: true,
	});

	const user = await getMe();

	expect(user?.display_name).toBe("Viewer");
});

test("getMe treats 401 as signed-out, not an error", async () => {
	stubFetch(401, { detail: "Not authenticated" });

	expect(await getMe()).toBeNull();
});

test("getMe still throws on non-401 failures", async () => {
	stubFetch(500, { detail: "boom" });

	await expect(getMe()).rejects.toBeInstanceOf(ApiError);
});

test("ApiError carries status and backend detail", async () => {
	stubFetch(401, { detail: "Invalid email or password" });

	const error = await loginLocal("a@b.c", "wrong").catch(
		(caught: unknown) => caught,
	);

	expect(error).toBeInstanceOf(ApiError);
	if (error instanceof ApiError) {
		expect(error.status).toBe(401);
		expect(error.message).toBe("Invalid email or password");
	}
});

test("loginLocal posts credentials as JSON", async () => {
	const mock = stubFetch(200, {
		id: 1,
		display_name: "Viewer",
		avatar_url: null,
		is_admin: false,
	});

	await loginLocal("a@b.c", "pw");

	expect(mock).toHaveBeenCalledWith("/api/v1/auth/local", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ email: "a@b.c", password: "pw" }),
	});
});

test("logout tolerates the empty 204 body", async () => {
	const mock = stubFetch(204);

	await expect(logout()).resolves.toBeUndefined();
	expect(mock).toHaveBeenCalledWith("/api/v1/auth/logout", { method: "POST" });
});

test("admin settings replacement uses a typed JSON PUT with same-origin credentials", async () => {
	const body = {
		region: "US",
		service_ids: [8],
		disabled_rail_types: ["genres" as const],
		appearance: { theme: "light" as const, accent: "azure" as const },
	};
	const mock = stubFetch(200, { settings: body, rail_types: [] });

	await saveSettings(body);

	expect(mock).toHaveBeenCalledWith("/api/v1/settings", {
		method: "PUT",
		credentials: "same-origin",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
});

test("service region is normalized and query encoded", async () => {
	const mock = stubFetch(200, { region: "US", services: [] });
	await getServices("us");
	expect(mock).toHaveBeenCalledWith("/api/v1/services?region=US", undefined);
});

test("connection probes send only the allowlisted target", async () => {
	const mock = stubFetch(200, {
		target: "seerr",
		ok: true,
		detail: "Connection successful",
	});
	await testConnection("seerr");
	expect(mock).toHaveBeenCalledWith("/api/v1/connection-test", {
		method: "POST",
		credentials: "same-origin",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ target: "seerr" }),
	});
});

test.each([
	401, 403, 422, 429, 500,
])("admin failures preserve status %i", async (status) => {
	stubFetch(status, { detail: "generic failure" });
	const error = await getServices("US").catch((caught: unknown) => caught);
	expect(error).toBeInstanceOf(ApiError);
	expect((error as ApiError).status).toBe(status);
	expect((error as ApiError).message).toBe("generic failure");
});
