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

from kmstat import app, db
from kmstat.models import SolarSystem, ItemType, Player, Character, Killmail
from kmstat.api import api
from kmstat.config import config


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
    nan_player = Player(title="__查无此人__")
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

        click.echo(f"Downloading killmails for {date} from {url}")

        if not download_with_retry(url, file_path):
            raise Exception("Failed to download killmail data")

        click.echo(f"Downloaded to {file_path}")

        # Extract the file
        click.echo(f"Extracting {file_path}")
        with tarfile.open(file_path, "r:bz2") as tar:
            tar.extractall(path=temp_dir)

        extracted_dir = Path(f"{temp_dir}/killmails")
        click.echo(f"Extracted to {extracted_dir}")

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
                            click.echo(f"Inserted killmail {killmail_id} into database")
                        else:
                            click.echo(
                                f"Warning: Character {character_id} not found in ESI"
                            )
                            click.echo(f"Skipping killmail {killmail_id}")

            # Remove the processed file
            os.remove(json_file)

        # Clean up the extracted directory
        os.rmdir(extracted_dir)

        # Optionally delete the downloaded tar file
        os.remove(file_path)

        click.echo(
            f"Processed {processed_count} killmails, inserted {inserted_count} into database"
        )

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error: {e}")


@app.cli.command()
def parseall():
    """
    Parse killmails from config.latest date (inclusive) to today.
    Stops immediately if killmail data is unavailable or if parsing fails.
    Updates config.latest after each successful parse.
    """
    try:
        # Get the starting date from config, backtrace 3 days for completeness
        start_date = config.latest - timedelta(days=3)
        end_date = date.today()

        if start_date > end_date:
            click.echo("No new data to parse: start date is after end date")
            return

        current_date = start_date
        while current_date <= end_date:
            # Check if data is available for this date
            response = api.session.head(kmurl(current_date))
            if response.status_code != 200:
                click.echo(f"\nInfo: No data available for {current_date}")
                click.echo("Stopping parseall due to unavailable data")
                return

            click.echo(f"\nProcessing date: {current_date}")
            try:
                # Call parse command for the current date
                ctx = click.get_current_context()
                ctx.invoke(parse, date=current_date.isoformat())
                # Update the latest date in config after successful parse
                config.set_latest(current_date)
            except Exception as e:
                click.echo(f"\nError occurred while parsing {current_date}: {e}")
                click.echo("Stopping parseall due to parse error")
                return

            # Move to next day
            current_date += timedelta(days=1)

        click.echo("\nFinished processing all available dates")

    except Exception as e:
        click.echo(f"Error in parseall: {e}")
        return


@app.cli.command()
@click.option("--char", help="Character Name to update. (remember to use quotes)")
@click.option("--title", help="Title to update.")
def updateplayer(char, title):
    """
    Update the player for a character based on title.
    If title is not provided, use the character's existing title.
    Will force create a new player if one doesn't exist with the given title.
    """
    try:
        character = Character.query.filter_by(name=char).first()
        if character:
            if character.updatePlayer(title, force_create=True):
                click.echo(f"Updated player for {char} with title '{title}'")
            else:
                click.echo(f"Failed to update player for {char}")
        else:
            click.echo(f"Character {char} not found in database")
    except Exception as e:
        db.session.rollback()
        click.echo(f"Error updating player: {e}")


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

        click.echo(f"Processing {total_systems} solar systems")

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
                    f"Added {len(systems_to_add)} new systems from batch {i+1} to {end}"
                )

        # Commit the changes to the database
        db.session.commit()
        click.echo(
            f"Solar systems database updated successfully. Added {new_systems} new systems."
        )

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error updating solar systems database: {e}")

    try:
        url = f"{FUZZWORK_URL}/invTypes.csv.bz2"
        click.echo(f"Downloading item types data from {url}")

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

        click.echo(f"Processing {total_items} item types")

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
                    f"Added {len(items_to_add)} new items from batch {i+1} to {end}"
                )

        # Commit the changes to the database
        db.session.commit()
        click.echo(
            f"Item types database updated successfully. Added {new_items} new items."
        )

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error updating item types database: {e}")

    # Update the config to mark sde update date
    config.set_sdeversion(date.today())
