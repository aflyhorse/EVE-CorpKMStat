"""
API client for EVE Online ESI.
"""

import requests
import time
from threading import Lock


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

    def get_alliance_id(self, corporation_id) -> int:
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

    def get_killmail_value(self, killmail_id) -> float:
        """
        Get the value of a killmail from zKillboard API.
        """
        url = f"{self.ZKB_ENDPOINT}/killID/{killmail_id}/"
        response = self._make_request("GET", url)
        if response.status_code == 200:
            data = response.json()
            # zKillboard API returns a list of killmails
            if isinstance(data, list) and len(data) > 0:
                return data[0].get("zkb", {}).get("totalValue")
            return None
        return None


# Create a single instance to be used throughout the application
api = API()
