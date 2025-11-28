"""
Application configuration.
"""

import os
import pytz
from configparser import ConfigParser
from datetime import datetime
from kmstat.models import SystemState


class Config:

    def __init__(self, config_file="instance/config.ini"):
        self.config_file = config_file
        self.config = ConfigParser()
        self.config.read(self.config_file)

        self.hoster = self.config.get("DEFAULT", "hoster")
        self.corporation_id = self.config.getint("DEFAULT", "corporation_id")
        self.sitename = self.config.get(
            "DEFAULT", "sitename", fallback="EVE Corp KM Stats"
        )
        self.footer = self.config.get(
            "DEFAULT", "footer", fallback="copyright 2025 aflyhorse"
        )

        from kmstat.api import api

        # Set User-Agent with hoster email (must be done after api is imported but before any API calls)
        api.set_user_agent(self.hoster)

        # if instance/logo.png not exist, download it
        if not os.path.exists("kmstat/static/logo.png"):
            os.makedirs("kmstat/static", exist_ok=True)
            api.save_corporation_logo(self.corporation_id, "kmstat/static/logo.png")

        if not self.config.has_option("DEFAULT", "alliance_id") or not self.config.get(
            "DEFAULT", "alliance_id"
        ):
            self.alliance_id = api.get_alliance_id(self.corporation_id)
            self.config.set("DEFAULT", "alliance_id", str(self.alliance_id))
            with open(self.config_file, "w") as configfile:
                self.config.write(configfile)
        else:
            self.alliance_id = self.config.getint("DEFAULT", "alliance_id")

        self.isIndependent = self.alliance_id == 0

        self.localtz = pytz.timezone(
            self.config.get("DEFAULT", "localtz", fallback="Asia/Shanghai")
        )
        self.startupdate = datetime.strptime(
            self.config.get("DEFAULT", "startupdate"), "%Y-%m-%d"
        ).date()

    @property
    def sdeversion(self):
        """Get the SDE version date from the database"""
        sde_date = SystemState.get_sde_version()
        if not sde_date:
            # Default to 1970-01-01 if not set
            sde_date = datetime.strptime("1970-01-01", "%Y-%m-%d").date()
        return sde_date

    def set_sdeversion(self, version_date):
        """Set the SDE version date in the database"""
        SystemState.set_sde_version(version_date)

    @property
    def latest(self):
        """Get the latest update date from the database"""
        latest_date = SystemState.get_latest_update()
        return latest_date if latest_date else self.startupdate

    def set_latest(self, latest: datetime):
        """Set the latest update date in the database"""
        SystemState.set_latest_update(latest)


# Create a single instance to be used throughout the application
config = Config()
