"""
Application configuration.
"""

import os
import pytz
from configparser import ConfigParser
from datetime import datetime


class Config:

    def __init__(self, config_file="instance/config.ini"):
        self.config_file = config_file
        self.config = ConfigParser()
        self.config.read(self.config_file)

        self.hoster = self.config.get("DEFAULT", "hoster")
        self.corporation_id = self.config.getint("DEFAULT", "corporation_id")
        self.sitename = self.config.get("DEFAULT", "sitename", fallback="EVE Corp KM Stats")

        from kmstat.api import api

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

        latest = self.config.get("STATUS", "latest")
        if latest:
            self.latest = datetime.strptime(
                latest,
                "%Y-%m-%d",
            ).date()
        else:
            self.latest = self.startupdate

        sdeversion = self.config.get("STATUS", "sdeversion", fallback="1970-01-01")
        if sdeversion:
            self.sdeversion = datetime.strptime(
                sdeversion,
                "%Y-%m-%d",
            ).date()
        else:
            self.sdeversion = datetime.strptime(
                "1970-01-01",
                "%Y-%m-%d",
            ).date()

    def set_latest(self, latest: datetime):
        self.latest = latest
        self.config.set("STATUS", "latest", latest.strftime("%Y-%m-%d"))
        with open(self.config_file, "w") as configfile:
            self.config.write(configfile)

    def set_sdeversion(self, sdeversion: datetime):
        self.sdeversion = sdeversion
        self.config.set("STATUS", "sdeversion", sdeversion.strftime("%Y-%m-%d"))
        with open(self.config_file, "w") as configfile:
            self.config.write(configfile)


# Create a single instance to be used throughout the application
config = Config()
