"""
Command line interface for the application.
"""

from datetime import date, datetime, timedelta
import os
import tarfile
from pathlib import Path
import pytz
import pandas as pd
import bz2
import io
import json
import time
import click
import secrets
import string

from kmstat import app, db
from kmstat.models import SolarSystem, ItemType, Player, Character, Killmail, User
from kmstat.api import api
from kmstat.config import config

nan_player_name = "__查无此人__"


@app.cli.command()
@click.option("--drop", is_flag=True, help="Create after drop.")
def initdb(drop):
    """
    Initialize the database.
    If --drop is specified, drop the existing database first.
    """
    if drop:
        db.drop_all()
    db.create_all()
    nan_player = Player(title=nan_player_name)
    db.session.add(nan_player)
    db.session.commit()
    click.echo("Initialized database.")


def kmurl(date: date) -> str:
    """
    Generate the URL for the killmails based on the given date.
    """
    year = date.year
    month = f"{date.month:02d}"
    day = f"{date.day:02d}"
    return f"https://data.everef.net/killmails/{year}/killmails-{year}-{month}-{day}.tar.bz2"


def download_with_retry(url: str, file_path: Path, max_retries: int = 3) -> bool:
    """
    Download a file with retry logic.
    Returns True if download was successful, False otherwise.
    """
    for attempt in range(max_retries):
        try:
            response = api.session.get(url, stream=True)
            response.raise_for_status()

            # Delete partially downloaded file if it exists
            if file_path.exists():
                file_path.unlink()

            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True

        except Exception as e:
            if attempt < max_retries - 1:
                retry_delay = (attempt + 1) * 5  # Exponential backoff
                click.echo(
                    f"Download failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                click.echo(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                click.echo(f"Download failed after {max_retries} attempts: {e}")
                # Clean up partial download if it exists
                if file_path.exists():
                    file_path.unlink()
                return False
    return False


@app.cli.command()
@click.argument("date", default=date.today().isoformat())
def parse(date):
    """
    Parse and download killmails for a given date.
    If no date is provided, defaults to today.
    """
    try:
        # Parse the date string
        parsed_date = datetime.fromisoformat(date)
        url = kmurl(parsed_date)

        # Create temp directory if it doesn't exist
        temp_dir = Path("instance/temp")
        temp_dir.mkdir(exist_ok=True)

        # Download file path
        file_path = temp_dir / f"killmails-{parsed_date.strftime('%Y-%m-%d')}.tar.bz2"

        click.echo(f"Info: Downloading killmails for {date} from {url}")

        if not download_with_retry(url, file_path):
            raise Exception("Error: Failed to download killmail data")

        # Extract the file
        click.echo(f"Info: Extracting {file_path}")
        with tarfile.open(file_path, "r:bz2") as tar:
            tar.extractall(path=temp_dir)

        extracted_dir = Path(f"{temp_dir}/killmails")
        click.echo(f"Info: Extracted to {extracted_dir}")

        # Process each file in the extracted directory
        processed_count = 0
        inserted_count = 0

        for json_file in Path(extracted_dir).glob("*.json"):
            processed_count += 1

            with open(json_file, "r") as f:
                killmail_data = json.load(f)

                # Find the attacker with final_blow: true
                final_blow_attacker = None
                for attacker in killmail_data.get("attackers", []):
                    if attacker.get("final_blow") is True:
                        final_blow_attacker = attacker
                        break

                # If we found the final blow attacker and they meet our criteria
                if (
                    final_blow_attacker
                    and final_blow_attacker.get("corporation_id")
                    == config.corporation_id
                    and (
                        (
                            config.isIndependent
                            and killmail_data.get("victim", {}).get("corporation_id")
                            == config.corporation_id
                        )
                        or (
                            not config.isIndependent
                            and killmail_data.get("victim", {}).get("alliance_id")
                            != config.alliance_id
                        )
                    )
                ):

                    # Extract the data we need
                    killmail_id = killmail_data.get("killmail_id")

                    # Convert UTC time to Asia/Shanghai timezone
                    utc_time = datetime.strptime(
                        killmail_data.get("killmail_time"), "%Y-%m-%dT%H:%M:%SZ"
                    )
                    utc_time = utc_time.replace(tzinfo=pytz.UTC)
                    killmail_time = utc_time.astimezone(config.localtz)

                    character_id = final_blow_attacker.get("character_id")
                    solar_system_id = killmail_data.get("solar_system_id")
                    victim_ship_type_id = killmail_data.get("victim", {}).get(
                        "ship_type_id"
                    )

                    # Check if this killmail already exists
                    existing_killmail = Killmail.query.filter_by(id=killmail_id).first()

                    if not existing_killmail:
                        # Get or create character using API
                        character = Character.query.filter_by(id=character_id).first()

                        # If character doesn't exist, try to get it from ESI
                        if not character and character_id:
                            character = api.get_character(character_id)
                            if character:
                                # Try to update player based on character title
                                if character.title is None:
                                    # Fallback to default player
                                    character.player = Player.query.first()
                                elif not character.updatePlayer():
                                    msg = f"Warning: Could not associate character {character.name}"
                                    msg += " with a player"
                                    click.echo(msg)
                                db.session.add(character)

                        # If we have a valid character (either existing or new), create the killmail
                        if character:
                            new_killmail = Killmail(
                                id=killmail_id,
                                killmail_time=killmail_time,
                                character_id=character_id,
                                solar_system_id=solar_system_id,
                                victim_ship_type_id=victim_ship_type_id,
                                total_value=api.get_killmail_value(killmail_id),
                            )
                            db.session.add(new_killmail)
                            db.session.commit()
                            inserted_count += 1
                            click.echo(f"Info: Inserted killmail {killmail_id}")
                        else:
                            click.echo(
                                f"Warning: Character {character_id} not found in ESI"
                            )
                            click.echo(f"Warning: Skipping killmail {killmail_id}")

            # Remove the processed file
            os.remove(json_file)

        # Clean up the extracted directory
        os.rmdir(extracted_dir)

        # Optionally delete the downloaded tar file
        os.remove(file_path)

        click.echo(
            f"Info: Processed {processed_count} killmails, inserted {inserted_count} into database"
        )

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error: {e}")


@app.cli.command()
@click.option(
    "--start",
    default=(config.latest - timedelta(days=3)).isoformat(),
    help="Start date (YYYY-MM-DD)",
)
@click.option("--end", default=date.today().isoformat(), help="End date (YYYY-MM-DD)")
def parseall(start, end):
    """
    Parse killmails between start and end dates (inclusive).
    Stops immediately if killmail data is unavailable or if parsing fails.
    """
    try:
        start_date = datetime.fromisoformat(start).date()
        end_date = datetime.fromisoformat(end).date()

        if start_date > end_date:
            click.echo("Error: Invalid date range: start date is after end date")
            return

        current_date = start_date
        while current_date <= end_date:
            # Check if data is available for this date
            response = api.session.head(kmurl(current_date))
            if response.status_code != 200:
                click.echo(f"\nInfo: No data available for {current_date}")
                click.echo("Info: Stopping parseall due to unavailable data")
                return

            click.echo(f"\nInfo: Processing date: {current_date}")
            try:
                # Call parse command for the current date
                ctx = click.get_current_context()
                ctx.invoke(parse, date=current_date.isoformat())
                # Update the latest date in config if it is outdated
                if current_date > config.latest:
                    config.set_latest(current_date)
            except Exception as e:
                click.echo(f"\nError: Error occurred while parsing {current_date}: {e}")
                click.echo("Info: Stopping parseall due to parse error")
                return

            # Move to next day
            current_date += timedelta(days=1)

        click.echo("\nInfo: Finished processing all available dates")

    except Exception as e:
        click.echo(f"Error: Error in parseall: {e}")
        return


@app.cli.command()
@click.option(
    "--char", required=True, help="Character Name to update. (remember to use quotes)"
)
@click.option("--title", help="Title to update.")
def updateplayer(char: str, title=nan_player_name):
    """
    Update the player for a character based on title.
    First updates the character's title, then associates with a player.
    Will create a new player if none exists with the given title.
    Updates join dates for both old and new players when moving characters.
    """
    try:
        character = Character.query.filter_by(name=char).first()
        if character:
            # Store the old player reference before updating
            old_player = character.player

            if character.updatePlayer(title):
                click.echo(f"Updated player for {char} with title '{character.title}'")

                # Update join date for the old player if it exists and is different
                if old_player and old_player != character.player:
                    _update_old_player_join_date(old_player)
            else:
                click.echo(f"Failed to update player for {char}")
        else:
            click.echo(f"Character {char} not found in database")
    except Exception as e:
        db.session.rollback()
        click.echo(f"Error updating player: {e}")


def _update_old_player_join_date(old_player):
    """
    Update the old player's join date after a character has been moved.
    Recalculates the join date based on remaining characters.
    """
    try:
        # Get all remaining characters for the old player that have join dates
        characters_with_dates = [
            c for c in old_player.characters if c.joindate is not None
        ]

        if characters_with_dates:
            # Find the earliest join date among remaining characters
            earliest_date = min(c.joindate for c in characters_with_dates)
            old_join_date = old_player.joindate

            if old_join_date != earliest_date:
                old_player.joindate = earliest_date
                db.session.add(old_player)
                click.echo(
                    f"Info: Updated old player {old_player.title} join date to {earliest_date}"
                )
            else:
                click.echo(f"Info: Old player {old_player.title} join date unchanged")
        else:
            # No characters with join dates remaining, set to None or keep existing
            if old_player.joindate is not None:
                old_player.joindate = None
                db.session.add(old_player)
                click.echo(
                    f"Info: Cleared join date for old player {old_player.title} (no characters with dates)"
                )

        # Update main character for old player
        old_player.update_main_character()

    except Exception as e:
        click.echo(f"Warning: Error updating old player join date: {str(e)}")


@app.cli.command()
def updatesde():
    """
    Update solar systems and item types database from CCP SDE.
    """
    FUZZWORK_URL = "https://www.fuzzwork.co.uk/dump/latest"
    try:
        url = f"{FUZZWORK_URL}/mapSolarSystems.csv.bz2"
        click.echo(f"Downloading solar systems data from {url}")

        # Download the compressed file using API session
        response = api.session.get(url)
        response.raise_for_status()

        # Decompress and load into pandas
        decompressed_data = bz2.decompress(response.content)
        df = pd.read_csv(io.BytesIO(decompressed_data))

        # Select only the columns we need
        systems_data = df[["solarSystemID", "solarSystemName"]].values

        # Process in batches for better performance
        batch_size = 1000
        total_systems = len(systems_data)

        click.echo(f"Info: Processing {total_systems} solar systems")

        # Get existing system IDs
        existing_ids = set(
            system.id
            for system in SolarSystem.query.with_entities(SolarSystem.id).all()
        )
        new_systems = 0

        # Add new records in batches
        for i in range(0, total_systems, batch_size):
            end = min(i + batch_size, total_systems)
            batch = systems_data[i:end]

            # Filter out existing systems
            systems_to_add = [
                SolarSystem(id=int(system[0]), name=system[1])
                for system in batch
                if int(system[0]) not in existing_ids
            ]

            if systems_to_add:
                db.session.add_all(systems_to_add)
                new_systems += len(systems_to_add)
                click.echo(
                    f"Info: Added {len(systems_to_add)} new systems from batch {i+1} to {end}"
                )

        # Commit the changes to the database
        db.session.commit()
        click.echo(
            f"Info:  Solar systems database updated successfully. Added {new_systems} new systems."
        )

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error: Error updating solar systems database: {e}")

    try:
        url = f"{FUZZWORK_URL}/invTypes.csv.bz2"
        click.echo(f"Info: Downloading item types data from {url}")

        # Download the compressed file using API session
        response = api.session.get(url)
        response.raise_for_status()

        # Decompress and load into pandas
        decompressed_data = bz2.decompress(response.content)
        df = pd.read_csv(io.BytesIO(decompressed_data))

        # Select only the columns we need
        item_types_data = df[["typeID", "typeName"]].values

        # Process in batches for better performance
        batch_size = 1000
        total_items = len(item_types_data)

        click.echo(f"Info: Processing {total_items} item types")

        # Get existing item type IDs
        existing_ids = set(
            item.id for item in ItemType.query.with_entities(ItemType.id).all()
        )
        new_items = 0

        # Add new records in batches
        for i in range(0, total_items, batch_size):
            end = min(i + batch_size, total_items)
            batch = item_types_data[i:end]

            # Filter out existing items
            items_to_add = [
                ItemType(id=int(item[0]), name=item[1])
                for item in batch
                if int(item[0]) not in existing_ids
            ]

            if items_to_add:
                db.session.add_all(items_to_add)
                new_items += len(items_to_add)
                click.echo(
                    f"Info: Added {len(items_to_add)} new items from batch {i+1} to {end}"
                )

        # Commit the changes to the database
        db.session.commit()
        click.echo(
            f"Info: Item types database updated successfully. Added {new_items} new items."
        )

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error: Error updating item types database: {e}")

    # Update the config to mark sde update date
    config.set_sdeversion(date.today())


@app.cli.command()
def updatejoindate():
    """
    Update join dates for all characters and players.
    Fetches corporation join dates from ESI for all characters,
    then updates player join dates to the earliest of their associated characters.
    """
    try:
        characters = Character.query.all()
        updated_characters = 0
        failed_characters = 0

        click.echo(f"Info: Processing {len(characters)} characters...")

        for i, character in enumerate(characters, 1):
            # Show progress every 10 characters or for the last one
            if i % 10 == 0 or i == len(characters):
                click.echo(
                    f"Progress: {i}/{len(characters)} characters processed", nl=False
                )
                click.echo("\r", nl=False)

            # Get the character's corporation join date
            join_date = api.get_character_corp_join_date(
                character.id, config.corporation_id
            )

            if join_date:
                # Normalize timezones for comparison - convert API date to naive datetime
                if join_date.tzinfo is not None:
                    join_date_naive = join_date.replace(tzinfo=None)
                else:
                    join_date_naive = join_date

                # Only update if the join date is different (comparing naive datetimes)
                if character.joindate != join_date_naive:
                    character.joindate = join_date_naive
                    db.session.add(character)
                    updated_characters += 1
                    click.echo(
                        f"Info: Updated {character.name} join date to {join_date_naive}"
                    )
            else:
                failed_characters += 1
                click.echo(f"Warning: Could not get join date for {character.name}")

        # Commit character updates
        db.session.commit()
        click.echo(
            f"Info: Updated {updated_characters} characters, {failed_characters} failed"
        )

        # Now update player join dates
        players = Player.query.all()
        updated_players = 0

        click.echo(f"Info: Processing {len(players)} players...")

        for player in players:
            # Skip the default "__查无此人__" player
            if player.title == nan_player_name:
                continue

            # Get all characters for this player that have join dates
            characters_with_dates = [
                c for c in player.characters if c.joindate is not None
            ]

            if characters_with_dates:
                # Find the earliest join date among all characters
                earliest_date = min(c.joindate for c in characters_with_dates)
                # Only update if the join date is different
                if player.joindate != earliest_date:
                    player.joindate = earliest_date
                    db.session.add(player)
                    updated_players += 1
                    click.echo(
                        f"Info: Updated player {player.title} join date to {earliest_date}"
                    )

        # Commit player updates
        db.session.commit()
        click.echo(f"Info: Updated {updated_players} players")
        click.echo("Info: Join date update completed successfully")

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error: Error updating join dates: {e}")


@app.cli.command()
def updatemainchar():
    """
    Update main character for all players.
    Sets the main character to the one with the earliest join date.
    If no characters have join dates, uses the first character.
    """
    try:
        players = Player.query.all()
        updated_players = 0

        click.echo(f"Info: Processing {len(players)} players...")

        for player in players:
            # Skip the default "__查无此人__" player
            if player.title == nan_player_name:
                continue

            # Skip players with no characters
            if not player.characters:
                click.echo(f"Warning: Player {player.title} has no characters")
                continue

            old_main = player.mainchar.name if player.mainchar else "None"

            # Update main character using the model method
            player.update_main_character()

            new_main = player.mainchar.name if player.mainchar else "None"

            if old_main != new_main:
                db.session.add(player)
                updated_players += 1
                click.echo(
                    f"Info: Updated main character for {player.title}: {old_main} -> {new_main}"
                )
            else:
                click.echo(
                    f"Info: Main character for {player.title} unchanged: {new_main}"
                )

        # Commit updates
        db.session.commit()
        click.echo(f"Info: Updated main character for {updated_players} players")
        click.echo("Info: Main character update completed successfully")

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error: Error updating main characters: {e}")


@app.cli.group()
def user():
    """User management commands."""
    pass


@user.command()
@click.argument("username")
@click.option(
    "--password",
    help="Password for the user. If not provided, a random password will be generated.",
)
def add(username, password):
    """Add a new user."""
    try:
        # Check if user already exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            click.echo(f"Error: User '{username}' already exists")
            return

        # Generate random password if not provided
        if not password:
            password = generate_random_password()
            click.echo(f"Info: Generated random password: {password}")

        # Create new user
        new_user = User(username=username)
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        click.echo(f"Success: User '{username}' created successfully")
        if not click.get_text_stream(
            "stdin"
        ).isatty():  # If password was auto-generated
            click.echo(f"Password: {password}")

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error: Failed to create user: {str(e)}")


@user.command()
@click.argument("username")
@click.option(
    "--new-password",
    help="New password for the user. If not provided, a random password will be generated.",
)
def modify(username, new_password):
    """Modify an existing user's password."""
    try:
        user = User.query.filter_by(username=username).first()
        if not user:
            click.echo(f"Error: User '{username}' not found")
            return

        # Generate random password if not provided
        if not new_password:
            new_password = generate_random_password()
            click.echo(f"Info: Generated random password: {new_password}")

        user.set_password(new_password)
        db.session.commit()

        click.echo(f"Success: Password for user '{username}' updated successfully")
        click.echo(f"New password: {new_password}")

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error: Failed to modify user: {str(e)}")


@user.command()
@click.argument("username")
@click.confirmation_option(prompt="Are you sure you want to delete this user?")
def delete(username):
    """Delete an existing user."""
    try:
        user = User.query.filter_by(username=username).first()
        if not user:
            click.echo(f"Error: User '{username}' not found")
            return

        db.session.delete(user)
        db.session.commit()

        click.echo(f"Success: User '{username}' deleted successfully")

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error: Failed to delete user: {str(e)}")


@user.command()
def list():
    """List all users."""
    try:
        users = User.query.all()
        if not users:
            click.echo("No users found")
            return

        click.echo("Users:")
        for user in users:
            click.echo(f"  - {user.username} (ID: {user.id})")

    except Exception as e:
        click.echo(f"Error: Failed to list users: {str(e)}")


def generate_random_password(length=12):
    """Generate a random password with specified length."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    password = "".join(secrets.choice(alphabet) for _ in range(length))
    return password


@app.cli.command()
@click.option(
    "--remove", is_flag=True, help="Remove dummy players (except the default player)."
)
def listdummyplayer(remove):
    """
    List all players that don't have any associated characters.
    These are typically dummy players created during data imports.
    Use --remove flag to delete them (except the default player).
    """
    try:
        # Query for players that have no associated characters, excluding the default player
        players_without_characters = Player.query.filter(
            ~Player.characters.any(), Player.title != nan_player_name
        ).all()

        if not players_without_characters:
            click.echo("No dummy players found (excluding default player).")
            return

        # All players in the list are removable since we already filtered out the default player
        removable_players = players_without_characters

        if remove:
            if not removable_players:
                click.echo("No dummy players to remove.")
                return

            # Confirm removal
            click.echo(f"Found {len(removable_players)} dummy player(s) to remove:")
            for player in removable_players:
                click.echo(f"  - {player.title} (ID: {player.id})")

            if click.confirm(
                f"\nAre you sure you want to delete {len(removable_players)} dummy player(s)?"
            ):
                removed_count = 0
                for player in removable_players:
                    db.session.delete(player)
                    removed_count += 1
                    click.echo(f"Removed player: {player.title}")

                db.session.commit()
                click.echo(f"Successfully removed {removed_count} dummy player(s).")
            else:
                click.echo("Operation cancelled.")
        else:
            # List mode
            click.echo(
                f"Found {len(players_without_characters)} dummy player(s) without associated characters:"
            )
            click.echo("-" * 60)

            for player in players_without_characters:
                joindate_str = (
                    player.joindate.strftime("%Y-%m-%d %H:%M:%S")
                    if player.joindate
                    else "No join date"
                )
                mainchar_str = (
                    player.mainchar.name if player.mainchar else "No main character"
                )

                click.echo(f"Player ID: {player.id}")
                click.echo(f"Title: {player.title}")
                click.echo(f"Join Date: {joindate_str}")
                click.echo(f"Main Character: {mainchar_str}")
                click.echo("-" * 60)

            if removable_players:
                click.echo(
                    f"\nNote: All {len(removable_players)} player(s) above can be removed with --remove flag."
                )

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error: Failed to process dummy players: {str(e)}")


@app.cli.command()
@click.option("--year", type=int, help="Year of the upload to fix")
@click.option("--month", type=int, help="Month of the upload to fix (1-12)")
@click.option("--all", "fix_all", is_flag=True, help="Fix all uploads")
def fixupload(year, month, fix_all):
    """
    Fix orphaned records (with negative character_id) by retrying ESI resolution.

    Can fix a specific upload by providing --year and --month, or fix all uploads with --all.

    Examples:
        flask fixupload --year 2025 --month 7
        flask fixupload --all
    """
    from kmstat.models import MonthlyUpload
    from kmstat.upload_service import MonthlyUploadService

    try:
        if fix_all:
            click.echo("Fixing orphaned records in all uploads...")
            stats = MonthlyUploadService.fix_orphaned_records()
        elif year and month:
            click.echo(f"Fixing orphaned records in {year}-{month:02d}...")
            upload = MonthlyUpload.query.filter_by(year=year, month=month).first()
            if not upload:
                click.echo(f"Error: No upload found for {year}-{month:02d}")
                return
            stats = MonthlyUploadService.fix_orphaned_records(upload)
        else:
            click.echo("Error: Please specify either --year and --month, or --all")
            click.echo("Usage: flask fixupload --year 2025 --month 7")
            click.echo("   or: flask fixupload --all")
            return

        # Display results
        click.echo("\n" + "=" * 60)
        click.echo("Fix Results:")
        click.echo("=" * 60)
        click.echo(f"Total records checked: {stats['total_checked']}")
        click.echo(f"Successfully fixed: {stats['fixed']}")
        click.echo(f"Failed to fix: {stats['failed']}")
        click.echo(f"Deleted (no name or not found): {stats['deleted']}")
        click.echo()

        if stats["total_checked"] > 0:
            click.echo("Breakdown by record type:")
            pap_stats = stats["by_type"]["pap"]
            click.echo(
                f"  PAP records: {pap_stats['fixed']} fixed, "
                f"{pap_stats['failed']} failed, {pap_stats['deleted']} deleted"
            )
            bounty_stats = stats["by_type"]["bounty"]
            click.echo(
                f"  Bounty records: {bounty_stats['fixed']} fixed, "
                f"{bounty_stats['failed']} failed, {bounty_stats['deleted']} deleted"
            )
            mining_stats = stats["by_type"]["mining"]
            click.echo(
                f"  Mining records: {mining_stats['fixed']} fixed, "
                f"{mining_stats['failed']} failed, {mining_stats['deleted']} deleted"
            )

        if stats["fixed"] > 0:
            click.echo(f"\n✓ Successfully fixed {stats['fixed']} orphaned record(s)")
        if stats["deleted"] > 0:
            click.echo(f"\n✓ Deleted {stats['deleted']} unfixable orphaned record(s)")
        if stats["failed"] > 0:
            click.echo(
                f"\n⚠ Failed to process {stats['failed']} record(s) - check logs for details"
            )
        if stats["total_checked"] == 0:
            click.echo("\n✓ No orphaned records found. Database is clean!")

    except Exception as e:
        click.echo(f"\nError: Failed to fix orphaned records: {str(e)}")
        import traceback

        traceback.print_exc()
