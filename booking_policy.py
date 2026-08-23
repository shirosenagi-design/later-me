"""Effective booking window policy for the localhost web bridge.

The canonical product minimum remains four hours. A fixed five-minute
minimum can be enabled only by an explicit development flag on a loopback
bound server. Private subprocess variables let ``web_api.py`` hand the
effective policy to the existing authoritative booking scripts.
"""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from typing import Mapping


DEFAULT_MINIMUM_MINUTES = 4 * 60
DEVELOPMENT_MINIMUM_MINUTES = 5
DEV_SHORT_HORIZON_ENV = "CALL_E_DEV_SHORT_HORIZON"
_EFFECTIVE_MINIMUM_ENV = "CALL_E_EFFECTIVE_MINIMUM_MINUTES"
_POLICY_MODE_ENV = "CALL_E_BOOKING_POLICY_MODE"


def _is_loopback(host: str) -> bool:
    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class BookingPolicy:
    minimum_minutes: int = DEFAULT_MINIMUM_MINUTES
    development_short_horizon_enabled: bool = False

    def require_compatible_bind_host(self, bind_host: str) -> None:
        if self.development_short_horizon_enabled and not _is_loopback(bind_host):
            raise ValueError(
                "Development short-horizon booking requires a loopback-only server."
            )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        bind_host: str,
    ) -> "BookingPolicy":
        env = os.environ if environment is None else environment
        raw = env.get(DEV_SHORT_HORIZON_ENV, "").strip()
        if raw not in {"", "0", "1"}:
            raise ValueError(
                f"{DEV_SHORT_HORIZON_ENV} must be 1 to enable or 0/unset to disable."
            )
        if raw != "1":
            return cls()
        policy = cls(
            minimum_minutes=DEVELOPMENT_MINIMUM_MINUTES,
            development_short_horizon_enabled=True,
        )
        policy.require_compatible_bind_host(bind_host)
        return policy

    def subprocess_environment(
        self,
        environment: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        child = dict(os.environ if environment is None else environment)
        child[_EFFECTIVE_MINIMUM_ENV] = str(self.minimum_minutes)
        child[_POLICY_MODE_ENV] = (
            "development_short_horizon"
            if self.development_short_horizon_enabled
            else "canonical"
        )
        return child


def effective_minimum_minutes(
    environment: Mapping[str, str] | None = None,
) -> int:
    """Read only the web bridge's bounded internal policy handoff."""
    env = os.environ if environment is None else environment
    mode = env.get(_POLICY_MODE_ENV, "canonical")
    value = env.get(_EFFECTIVE_MINIMUM_ENV)
    if mode == "development_short_horizon" and value == str(
        DEVELOPMENT_MINIMUM_MINUTES
    ):
        return DEVELOPMENT_MINIMUM_MINUTES
    return DEFAULT_MINIMUM_MINUTES
