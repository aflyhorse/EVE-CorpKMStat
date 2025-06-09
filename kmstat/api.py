"""
API client for EVE Online ESI.
"""

import requests
import time
from threading import Lock
from functools import wraps
import logging
from typing import Optional
from datetime import datetime


def retry_with_backoff(max_retries=3, initial_delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for retry in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except requests.HTTPError as e:
                    last_exception = e
                    # Check for 420 Error Limited status code
                    if (
                        hasattr(e, "response")
                        and e.response is not None
                        and e.response.status_code == 420
                    ):
                        if retry < max_retries - 1:
                            logging.warning(
                                f"ESI API rate limited (420), waiting 60 seconds before retry {retry + 1}/{max_retries}"
                            )
                            time.sleep(60)  # Wait 60 seconds for rate limit
                        else:
                            logging.error(
                                f"ESI API rate limited (420), exhausted all {max_retries} retries"
                            )
                    else:
                        # For other HTTP errors, use exponential backoff
                        if retry < max_retries - 1:
                            logging.warning(
                                "HTTP error "
                                + f"{e.response.status_code if hasattr(e, 'response') and e.response else 'unknown'}"
                                + f", retrying in {delay} seconds"
                            )
                            time.sleep(delay)
                            delay *= 2  # Exponential backoff
                except (requests.RequestException, ValueError) as e:
                    last_exception = e
                    if retry < max_retries - 1:  # Don't sleep on the last iteration
                        logging.warning(
                            f"Request error: {str(e)}, retrying in {delay} seconds"
                        )
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff

            logging.error(
                f"Error: Failed after {max_retries} retries: {last_exception}"
            )
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
        response = self.session.request(method, url, **kwargs)

        # Check for 420 Error Limited and raise HTTPError to trigger retry logic
        if response.status_code == 420:
            raise requests.HTTPError("420 Error Limited", response=response)

        return response

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
        Also fetches the corporation join date automatically.
        """
        url = f"{self.ESI_ENDPOINT}/characters/{character_id}/?datasource=tranquility"
        response = self._make_request("GET", url)
        if response.status_code == 200:
            from kmstat.models import Character
            from kmstat.config import config

            character_data = response.json()

            # Create character with basic info
            character = Character(
                id=character_id,
                name=character_data.get("name"),
                title=character_data.get("title", "").strip(),
            )

            # Try to get the corporation join date
            join_date = self.get_character_corp_join_date(
                character_id, config.corporation_id
            )
            if join_date:
                character.joindate = join_date
                logging.info(
                    f"Set join date for new character {character.name}: {join_date}"
                )
            else:
                logging.warning(
                    f"Could not get join date for new character {character.name}"
                )

            return character
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

    @retry_with_backoff()
    def get_character_id_by_name(self, character_name: str) -> Optional[int]:
        """
        Get character ID from character name using EVE Online ESI Universe IDs endpoint.

        Args:
            character_name (str): The name of the character to search for

        Returns:
            Optional[int]: The character ID if found and verified as a character, None otherwise
        """
        url = f"{self.ESI_ENDPOINT}/universe/ids/?datasource=tranquility"

        # The API expects a simple list of names to search for
        payload = [character_name]

        response = self._make_request("POST", url, json=payload)
        if response.status_code != 200:
            logging.warning(
                f"Failed to get character ID for '{character_name}', status code: {response.status_code}"
            )
            return None

        data = response.json()
        if not isinstance(data, dict):
            logging.warning(
                f"Invalid response format for character name '{character_name}'"
            )
            return None

        # Check if we have characters in the response
        characters = data.get("characters", [])
        if not characters:
            logging.warning(f"No character found for name '{character_name}'")
            return None

        # The API returns a list of character objects, we take the first one
        character = characters[0]

        return character.get("id")

    @retry_with_backoff()
    def get_character_corp_join_date(
        self, character_id: int, corporation_id: int
    ) -> Optional[datetime]:
        """
        Get the date when a character first joined a specific corporation using ESI Corporation History endpoint.

        Args:
            character_id (int): The character ID to get corporation history for
            corporation_id (int): The corporation ID to find the join date for

        Returns:
            Optional[datetime]: The datetime when the character first joined the corporation in local timezone,
                              None if not found
        """
        url = f"{self.ESI_ENDPOINT}/characters/{character_id}/corporationhistory/?datasource=tranquility"

        response = self._make_request("GET", url)
        if response.status_code != 200:
            logging.warning(
                f"Failed to get corporation history for character {character_id}, status code: {response.status_code}"
            )
            return None

        data = response.json()
        if not isinstance(data, list):
            logging.warning(
                f"Invalid response format for character {character_id} corporation history"
            )
            return None

        # Find the oldest occurrence (minimal record_id) of the character joining the specified corporation
        # Filter all records for the specified corporation
        corp_records = [
            record for record in data if record.get("corporation_id") == corporation_id
        ]

        if not corp_records:
            logging.info(
                f"Character {character_id} has never been in corporation {corporation_id}"
            )
            return None

        # Find the record with the minimal record_id (oldest join)
        oldest_record = min(
            corp_records, key=lambda x: x.get("record_id", float("inf"))
        )

        start_date = oldest_record.get("start_date")
        if start_date:
            try:
                # Parse the UTC datetime string (format: "2022-05-28T15:09:00Z")
                utc_datetime = datetime.fromisoformat(start_date.replace("Z", "+00:00"))

                # Get local timezone from config
                from kmstat.config import config

                local_datetime = utc_datetime.astimezone(config.localtz)

                logging.info(
                    f"Character {character_id} first joined corporation {corporation_id} "
                    f"on {local_datetime} ({config.localtz}) (record_id: {oldest_record.get('record_id')})"
                )
                return local_datetime
            except ValueError as e:
                logging.error(f"Failed to parse datetime '{start_date}': {e}")
                return None
        else:
            logging.warning(
                f"Found corporation record but no start_date for character {character_id}"
            )
            return None


# Create a single instance to be used throughout the application
api = API()
