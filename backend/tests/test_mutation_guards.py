"""Regression inventory for mutation CSRF/rate-limit dependencies."""

from collections.abc import Iterable
from typing import cast

from fastapi import APIRouter
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from tasterr.main import create_app
from tasterr.settings import Settings

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
READ_ONLY_POSTS = {("POST", "/api/v1/availability")}
EXPECTED_GUARDS = {
    ("POST", "/api/v1/auth/plex/pin"): {"require_same_origin", "login_rate_limit"},
    ("POST", "/api/v1/auth/plex/pin/poll"): {"require_same_origin"},
    ("POST", "/api/v1/auth/local"): {"require_same_origin", "login_rate_limit"},
    ("POST", "/api/v1/auth/logout"): {"require_same_origin", "mutation_rate_limit"},
    ("PUT", "/api/v1/settings"): {"require_same_origin", "admin_rate_limit"},
    ("POST", "/api/v1/connection-test"): {"require_same_origin", "admin_rate_limit"},
    ("POST", "/api/v1/request"): {"require_same_origin", "mutation_rate_limit"},
    ("POST", "/api/v1/signals"): {"require_same_origin", "mutation_rate_limit"},
    ("POST", "/api/v1/taste-onboarding"): {
        "require_same_origin",
        "mutation_rate_limit",
    },
    ("POST", "/api/v1/recommendations/reset"): {
        "require_same_origin",
        "mutation_rate_limit",
    },
    ("POST", "/api/v1/recommendations/household-blend"): {
        "require_same_origin",
        "mutation_rate_limit",
    },
}
AUTHENTICATED_MUTATIONS = {
    key
    for key in EXPECTED_GUARDS
    if key
    not in {
        ("POST", "/api/v1/auth/plex/pin"),
        ("POST", "/api/v1/auth/plex/pin/poll"),
        ("POST", "/api/v1/auth/local"),
    }
}


def _dependency_names(root: Dependant) -> set[str]:
    names: set[str] = set()
    pending = list(root.dependencies)
    while pending:
        dependency = pending.pop()
        call = dependency.call
        name = getattr(call, "__name__", None)
        if isinstance(name, str):
            names.add(name)
        pending.extend(dependency.dependencies)
    return names


def _api_routes() -> dict[tuple[str, str], APIRoute]:
    app = create_app(Settings())
    routes: dict[tuple[str, str], APIRoute] = {}

    def visit(entries: Iterable[BaseRoute], prefix: str = "") -> None:
        for route in entries:
            if isinstance(route, APIRoute):
                path = f"{prefix}{route.path}"
                if not path.startswith("/api/"):
                    continue
                for method in route.methods or set():
                    method_name = getattr(method, "value", str(method))
                    routes[(method_name, path)] = route
                continue

            # FastAPI defers included-router expansion; walk its original router
            # with the inclusion prefix instead of depending on the private class.
            original = getattr(route, "original_router", None)
            context = getattr(route, "include_context", None)
            if isinstance(original, APIRouter) and context is not None:
                nested_prefix = cast("str", getattr(context, "prefix", ""))
                visit(original.routes, f"{prefix}{nested_prefix}")

    visit(app.router.routes)
    return routes


def test_every_state_changing_route_has_its_designated_guards() -> None:
    routes = _api_routes()
    discovered = {
        key for key in routes if key[0] in MUTATING_METHODS and key not in READ_ONLY_POSTS
    }

    assert discovered == set(EXPECTED_GUARDS)
    for key, expected in EXPECTED_GUARDS.items():
        names = _dependency_names(routes[key].dependant)
        assert expected <= names, f"{key} is missing {sorted(expected - names)}"
        if key in AUTHENTICATED_MUTATIONS:
            assert "require_session" in names


def test_every_response_bearing_api_route_has_an_explicit_model() -> None:
    missing = {key for key, route in _api_routes().items() if route.response_model is None}
    assert missing == {("POST", "/api/v1/auth/logout")}  # intentional 204 response


def test_read_only_post_and_pin_poll_are_explicitly_exempt() -> None:
    routes = _api_routes()
    limited = {"login_rate_limit", "mutation_rate_limit", "admin_rate_limit"}

    availability = _dependency_names(routes[("POST", "/api/v1/availability")].dependant)

    # The old state-changing GET poll is gone; the replacement POST is guarded
    # by the same-origin check (login-CSRF defense) but stays exempt from the
    # tight login bucket — it polls every ~2s by design behind a 256-bit,
    # expiring, single-use handle.
    assert ("GET", "/api/v1/auth/plex/pin/{pin_id}") not in routes
    pin_poll = _dependency_names(routes[("POST", "/api/v1/auth/plex/pin/poll")].dependant)

    assert "require_session" in availability
    assert "require_same_origin" not in availability
    assert availability.isdisjoint(limited)
    assert "require_same_origin" in pin_poll
    assert pin_poll.isdisjoint(limited)
