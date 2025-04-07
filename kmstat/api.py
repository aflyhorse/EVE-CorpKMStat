"""
API client for EVE Online ESI.
"""

import requests
import time
from threading import Lock
from functools import wraps
import logging
from typing import Optional


def retry_with_backoff(max_retries=3, initial_delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for retry in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (requests.RequestException, ValueError) as e:
                    last_exception = e
                    if retry < max_retries - 1:  # Don't sleep on the last iteration
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff

            logging.error(f"Error: Failed after {max_retries} retries: {last_exception}")
            return None  # Return None after all retries are exhausted

        return wrapper

    return decorator


class API:

    limits_per_sec = 10
    ESI_ENDPOINT = "https://esi.evetech.net/latest"
    ESI_IMAGE = "https://images.evetech.net"
    ZKB_ENDPOINT = "https://zkillboard.com/api"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "EVE-CorpKMStat/1.0 (https://github.com/aflyhorse/EVE-CorpKMStat)",
            }
        )
        self._last_request_time = 0
        self._request_lock = Lock()
        self._min_interval = 1.0 / self.limits_per_sec

    def _enforce_rate_limit(self):
        """
        Enforces the rate limit by waiting if necessary.
        """
        with self._request_lock:
            current_time = time.time()
            time_since_last = current_time - self._last_request_time
            if time_since_last < self._min_interval:
                time.sleep(self._min_interval - time_since_last)
            self._last_request_time = time.time()

    def _make_request(self, method, url, **kwargs):
        """
        Makes a rate-limited request using the session.
        """
        self._enforce_rate_limit()
        return self.session.request(method, url, **kwargs)

    @retry_with_backoff()
    def get_alliance_id(self, corporation_id) -> Optional[int]:
        """
        Get the alliance ID for a given corporation ID from EVE Online ESI.
        """
        url = (
            f"{self.ESI_ENDPOINT}/corporations/{corporation_id}/?datasource=tranquility"
        )
        response = self._make_request("GET", url)
        if response.status_code == 200:
            return response.json().get("alliance_id", 0)
        return None

    @retry_with_backoff()
    def save_corporation_logo(self, corporation_id, image_path):
        """
        Save the corporation logo to a file.
        """
        url = f"{self.ESI_IMAGE}/corporations/{corporation_id}/logo"
        response = self._make_request("GET", url, stream=True)
        if response.status_code == 200:
            with open(image_path, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            return True
        return False

    @retry_with_backoff()
    def get_character(self, character_id):
        """
        Get character information from EVE Online ESI.
        """
        url = f"{self.ESI_ENDPOINT}/characters/{character_id}/?datasource=tranquility"
        response = self._make_request("GET", url)
        if response.status_code == 200:
            from kmstat.models import Character

            return Character(
                id=character_id,
                name=response.json().get("name"),
                title=response.json().get("title"),
            )
        return None

    @retry_with_backoff(max_retries=5, initial_delay=2)
    def get_killmail_value(self, killmail_id) -> Optional[float]:
        """
        Get the value of a killmail from zKillboard API.
        Returns:
            float: The total value of the killmail
            None: If the value cannot be retrieved after retries
        """
        url = f"{self.ZKB_ENDPOINT}/killID/{killmail_id}/"
        response = self._make_request("GET", url)
        if response.status_code != 200:
            raise requests.RequestException(
                f"Warning: Failed to get killmail value, status code: {response.status_code}"
            )

        data = response.json()
        if not isinstance(data, list) or not data:
            raise ValueError(f"Invalid response format for killmail {killmail_id}")

        value = data[0].get("zkb", {}).get("totalValue")
        if value is None:
            raise ValueError(f"No value found for killmail {killmail_id}")

        return float(value)  # Convert to float to ensure we don't return None


# Create a single instance to be used throughout the application
api = API()
