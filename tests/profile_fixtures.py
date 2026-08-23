from __future__ import annotations

from pathlib import Path

from user_profile import UserProfileStore


class ReversingTestProtector:
    """Test-only reversible transform; never selected by production code."""

    marker = b"CALL-E-TEST-PROFILE\x00"

    def protect(self, plaintext: bytes) -> bytes:
        return self.marker + plaintext[::-1]

    def unprotect(self, protected: bytes) -> bytes:
        if not protected.startswith(self.marker):
            raise ValueError("not a synthetic protected profile")
        return protected[len(self.marker) :][::-1]


def synthetic_phone() -> str:
    # Constructed at runtime so no dialable-looking fixture enters public source.
    return "+" + "999" + "0" * 9


def completed_profile_store(data_root: Path, language: str = "ja") -> UserProfileStore:
    store = UserProfileStore(
        data_root / "profile",
        protector=ReversingTestProtector(),
    )
    store.create_first_run(
        language=language,
        phone=synthetic_phone(),
        own_number_confirmed=True,
        future_calls_authorized=True,
    )
    return store
