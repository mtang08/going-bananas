"""Narrow adapter around Garmin's official Personal API Python package."""

import os
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import requests


class GarminConfigurationError(RuntimeError):
    pass


class GarminRemoteError(RuntimeError):
    """Safe remote failure metadata; never includes Garmin response body."""

    def __init__(self, status_code: int, retry_after: str | None):
        super().__init__(f"garmin_http_{status_code}")
        self.status_code = status_code
        self.response = SimpleNamespace(headers={"Retry-After": retry_after} if retry_after else {})


class GarminPersonalSource:
    def __init__(self, key_file: Path, token_cache_file: Path, timeout: int = 30):
        self.key_file = key_file
        self.token_cache_file = token_cache_file
        self.timeout = timeout
        self._auth: Any = None
        self._client: Any = None
        self._key: str | None = None
        self._retry_after: str | None = None
        self._http_session: requests.Session | None = None

    def __enter__(self) -> "GarminPersonalSource":
        try:
            from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator
        except ImportError as exc:
            raise GarminConfigurationError("official_garmin_client_not_installed") from exc
        env_key = os.environ.get("GARMIN_API_KEY") or os.environ.get("GARMIN_PERSONAL_API_KEY")
        if env_key:
            self._key = env_key.strip()
        else:
            if not self.key_file.is_file():
                raise GarminConfigurationError("garmin_key_file_missing")
            if self.key_file.stat().st_mode & 0o077:
                raise GarminConfigurationError("garmin_key_file_permissions")
            self._key = self.key_file.read_text(encoding="utf-8").strip()
        if not self._key:
            raise GarminConfigurationError("garmin_key_file_empty")
        self.token_cache_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.token_cache_file.parent.chmod(0o700)
        self._auth = PersonalApiAuthenticator(
            bearer_token_cache_file=self.token_cache_file, timeout=self.timeout
        )
        token = self._auth.obtain_token(self._key)
        self._http_session = requests.Session()
        self._http_session.hooks["response"].append(self._capture_response)
        self._client = GarminPersonalApiClient(token.access_token, timeout=self.timeout,
                                               session=self._http_session)
        return self

    def _capture_response(self, response: requests.Response, **_: object) -> requests.Response:
        self._retry_after = response.headers.get("Retry-After")
        return response

    def __exit__(self, *_: object) -> None:
        if self._client is not None:
            self._client.close()
        if self._auth is not None:
            self._auth.close()

    def search_page(self, start: int, limit: int, first: date, last: date) -> list[dict[str, Any]]:
        data = self._call(lambda: self._client.search_activities(
            start=start, limit=limit, start_date=first, end_date=last))
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise GarminConfigurationError("invalid_activity_page_shape")
        return data

    def _call(self, operation):
        from garmin_personal_api import HttpError

        def invoke():
            self._retry_after = None
            try:
                return operation()
            except HttpError as exc:
                raise GarminRemoteError(exc.status_code, self._retry_after) from None

        try:
            return invoke()
        except GarminRemoteError as exc:
            if exc.status_code != 401:
                raise
            token = self._auth.obtain_token(self._key, force_refresh=True)
            self._client.update_bearer_token(token.access_token)
            return invoke()

    def fetch_recovery(self, dataset: str, first: date, last: date) -> list[dict[str, Any]]:
        if dataset == "sleep":
            data = self._call(lambda: self._client.get_daily_sleep_summaries(first, last))
            if not isinstance(data, list):
                raise GarminConfigurationError("invalid_sleep_shape")
            return data
        if dataset == "hrv":
            data = self._call(lambda: self._client.get_daily_hrv_summaries(first, last))
            if not isinstance(data, dict) or not isinstance(data.get("hrvSummaries"), list):
                raise GarminConfigurationError("invalid_hrv_shape")
            owner = data.get("userProfilePk")
            return [{**item, "userProfilePk": owner} for item in data["hrvSummaries"]]
        if dataset == "resting_hr":
            data = [self._call(lambda day=first + timedelta(days=n): self._client.get_daily_heart_rate(day))
                    for n in range((last - first).days + 1)]
            if not all(isinstance(item, dict) for item in data):
                raise GarminConfigurationError("invalid_resting_hr_shape")
            return data
        raise GarminConfigurationError("unsupported_dataset")

    def pages(self, first: date, last: date, page_size: int = 50,
              max_pages: int = 200) -> Iterator[tuple[int, list[dict[str, Any]]]]:
        if first > last:
            raise ValueError("inverted_date_range")
        if page_size < 1 or page_size > 200 or max_pages < 1:
            raise ValueError("invalid_paging_limit")
        seen: set[tuple[str, ...]] = set()
        for page_number in range(max_pages):
            offset = page_number * page_size
            records = self.search_page(offset, page_size, first, last)
            signature = tuple(str(item.get("activityId")) for item in records)
            if records and signature in seen:
                raise GarminConfigurationError("repeated_activity_page")
            seen.add(signature)
            yield offset, records
            if len(records) < page_size:
                return
        raise GarminConfigurationError("activity_page_limit")
