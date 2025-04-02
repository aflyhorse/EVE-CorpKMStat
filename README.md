# README for EVE-CorpKMStat

## Project Overview

EVE-CorpKMStat is a Flask-based application designed to manage and analyze corporation statistics in the EVE Online universe. The application utilizes SQLAlchemy with SQLite as the database backend to store and retrieve data related to corporations.

## Usage

### First-time

1. Copy and edit ```instance/config.ini```.
2. Run ```flask initdb``` and ```flask flask updatesde``` to init database.

### After major update of Tranquility

1. Run ```flask updatesde``` to get updated SDE.

## Thanks

Many thanks for:
* [EVERef](https://everef.net) for packaged killmails.
* [Fuzzwork](https://www.fuzzwork.co.uk/) for CCP Static Data Export Conversions.
* [zKillboard](https://zkillboard.com/) for price estimation of killmail.

## License

This project is licensed under the GPLv3 License. See the LICENSE file for details.

EVE Online and the EVE logo are the registered trademarks of CCP hf. All rights are reserved worldwide. All other trademarks are the property of their respective owners. EVE Online, the EVE logo, EVE and all associated logos and designs are the intellectual property of CCP hf. All artwork, screenshots, characters, vehicles, storylines, world facts or other recognizable features of the intellectual property relating to these trademarks are likewise the intellectual property of CCP hf.