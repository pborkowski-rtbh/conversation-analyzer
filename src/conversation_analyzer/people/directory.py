"""Each user's department, from the map the associates indexer writes to its state bucket (§8.4)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError

from conversation_analyzer.docs.content import storage_client
from conversation_analyzer.settings import get_settings, now
from conversation_analyzer.vocab import DepartmentFamily


def email_of(principal: str | None) -> str | None:
    """The email in `user:<email>`, `principal://goog/subject/<email>` or a bare email (after the last `:` or `/`)."""
    email = (principal or "").strip().lower().rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    return email or None


@dataclass(frozen=True)
class Directory:
    """`email -> base_function` of every active associate; held in memory for one run, never stored."""

    departments: dict[str, str]
    families: dict[str, str] = field(init=False)  # base_function -> family code, the privacy floor applied
    stored: dict[str, str] = field(init=False)  # base_function -> the value stored for it

    def __post_init__(self) -> None:
        s = get_settings().strata
        family = {m: f for f, members in s.department_families.items() for m in members}
        size = Counter(family.get(b, DepartmentFamily.OTHER.value) for b in self.departments.values())
        floor = s.department_min_associates
        folded = {
            b: f if size[f] >= floor else DepartmentFamily.OTHER.value
            for b in set(self.departments.values())
            for f in [family.get(b, DepartmentFamily.OTHER.value)]
        }
        object.__setattr__(self, "families", folded)
        # The base_function is stored as is when listed in settings (the closed list); a new value as OTHER.
        kept = {b: b if b in family else DepartmentFamily.OTHER.value for b in set(self.departments.values())}
        object.__setattr__(self, "stored", kept)

    def base_function(self, principal: str | None) -> str | None:
        """The user's `base_function`; None for a user not in the map (service accounts, externals)."""
        email = email_of(principal)
        return self.departments.get(email) if email else None

    def family(self, principal: str | None) -> str:
        """The user's department family; a family under the privacy floor is OTHER, a user not in the map UNKNOWN."""
        b = self.base_function(principal)
        return DepartmentFamily.UNKNOWN.value if b is None else self.families[b]

    def stored_base_function(self, principal: str | None) -> str:
        """The `base_function` as stored: itself when listed in settings, else OTHER; UNKNOWN when not in the map."""
        b = self.base_function(principal)
        return DepartmentFamily.UNKNOWN.value if b is None else self.stored[b]


def split_uri(uri: str) -> tuple[str, str]:
    bucket, _, path = uri.removeprefix("gs://").partition("/")
    if not uri.startswith("gs://") or not bucket or not path:
        raise ValueError(f"not a gs://<bucket>/<path> URI: {uri!r}")
    return bucket, path


def load_directory(at: datetime | None = None) -> Directory | None:
    """The current map; None when it is missing, malformed or stale, and the run then counts every user UNKNOWN."""
    s = get_settings()
    bucket, path = split_uri(s.department_map_uri)
    try:
        data = json.loads(storage_client().bucket(bucket).blob(path).download_as_bytes())
    except (GoogleAPIError, GoogleAuthError, OSError, ValueError):  # OSError covers the transport's errors
        return None
    if not isinstance(data, dict):
        return None
    departments = data.get("departments")
    if (
        not isinstance(departments, dict)
        or not departments
        or data.get("count") != len(departments)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in departments.items())
    ):
        return None
    try:
        generated_at = datetime.fromisoformat(data["generated_at"])
    except (KeyError, TypeError, ValueError):
        return None
    # The indexer runs hourly; an older map means it has been failing, and its leavers and joiners are wrong.
    if generated_at.tzinfo is None or (at or now()) - generated_at > timedelta(hours=s.people_directory.max_age_hours):
        return None
    return Directory(departments)
