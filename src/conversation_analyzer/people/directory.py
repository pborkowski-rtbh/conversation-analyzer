"""Each user's department, from the map the associates indexer writes to its state bucket (§8.4)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from google.api_core.exceptions import GoogleAPIError

from conversation_analyzer.docs.content import storage_client
from conversation_analyzer.settings import get_settings, now


@dataclass(frozen=True)
class Directory:
    """`email -> base_function` of every active associate; held in memory for one run, never stored."""

    departments: dict[str, str]

    def base_function(self, principal: str | None) -> str | None:
        """The user's `base_function`; None for a user not in the map (service accounts, externals)."""
        email = (principal or "").removeprefix("user:").strip().lower()
        return self.departments.get(email) if email else None


def split_uri(uri: str) -> tuple[str, str]:
    bucket, _, path = uri.removeprefix("gs://").partition("/")
    if not uri.startswith("gs://") or not bucket or not path:
        raise ValueError(f"not a gs://<bucket>/<path> URI: {uri!r}")
    return bucket, path


def load_directory() -> Directory | None:
    """The current map; None when it is missing, malformed or stale, and the run then counts every user UNKNOWN."""
    s = get_settings()
    bucket, path = split_uri(s.env.department_map_uri)
    try:
        data = json.loads(storage_client().bucket(bucket).blob(path).download_as_bytes())
    except (GoogleAPIError, ValueError):
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
    if generated_at.tzinfo is None or now() - generated_at > timedelta(hours=s.people_directory.max_age_hours):
        return None
    return Directory(departments)
