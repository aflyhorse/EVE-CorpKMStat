# README for EVE-CorpKMStat

## Project Overview

EVE-CorpKMStat is a Flask-based application designed to manage and analyze corporation statistics in the EVE Online universe. The application utilizes SQLAlchemy with SQLite as the database backend to store and retrieve data related to corporations.

Player combination is based on in-game titles. The project *does not require CCP ESI* and rely only on public data.


## Example

[SMAC雪月城击杀榜](https://smac.lunes.faith)


## Usage

### First-time

1. Copy and edit ```instance/config.ini```.
1. Run ```flask initdb``` and ```flask updatesde``` to init database.
1. Run ```flask parseall``` and monitor its output.
3. Copy and edit ```scripts/kmstatdailyup``` to ```/etc/cron.daily/```.

### After major update of Tranquility

1. Run ```flask updatesde``` to get updated SDE.

### CLI tools

* Manually combine or create player is made via ```flask updateplayer --char [character name] --title [existing or new title]```.
* Use ```flask parseall --start [startdate] --end [enddate]``` to force update on given range.
* Use ```flask updatejoindate``` to update join dates for all characters and players.

### User Management

The application includes user authentication for accessing administrative features:

* Create a user: ```flask user add [username] --password [password]``` (if no password provided, random one will be generated)
* Modify user password: ```flask user modify [username] --new-password [password]``` (if no password provided, random one will be generated)
* Delete a user: ```flask user delete [username]```
* List all users: ```flask user list```

**Note**: Users can only change their own passwords via the web interface at `/change-password`. Registration is not available through the website - users must be created by administrators via CLI.


## About Me

I'm a long time EVE Online player, [Nadeko Hakomairos](https://evewho.com/character/94299194) of [Snow Moon City](https://evewho.com/corporation/98702000) of [Fraternity.](https://evewho.com/alliance/99003581)

This project is built to simplify the management of my corp. My corp provide monthly rewards based on kills made. Feel free to contact me in game if you have problems or want to join my corp. The corp is UTC+8 Chinese based.

In-game ISK donations are also appreciated :smile:


## Thanks

Many thanks for:
* [EVERef](https://everef.net) for packaged killmails.
* [Fuzzwork](https://www.fuzzwork.co.uk/) for CCP Static Data Export Conversions.
* [zKillboard](https://zkillboard.com/) for price estimation of killmail.


## License

This project is licensed under the GPLv3 License. See the LICENSE file for details.

EVE Online and the EVE logo are the registered trademarks of CCP hf. All rights are reserved worldwide. All other trademarks are the property of their respective owners. EVE Online, the EVE logo, EVE and all associated logos and designs are the intellectual property of CCP hf. All artwork, screenshots, characters, vehicles, storylines, world facts or other recognizable features of the intellectual property relating to these trademarks are likewise the intellectual property of CCP hf.
