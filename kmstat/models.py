"""
Database models for the application.
"""

from kmstat import db
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import click


class User(UserMixin, db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(nullable=False)

    def set_password(self, password: str):
        """Set password hash from plain text password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Check if provided password matches the hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"


class Player(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(nullable=False, unique=True)
    joindate: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    mainchar_id: Mapped[int] = mapped_column(
        db.ForeignKey("character.id"), nullable=True
    )
    mainchar: Mapped["Character"] = db.relationship(
        "Character", foreign_keys=[mainchar_id], post_update=True
    )
    characters: Mapped[list["Character"]] = db.relationship(
        "Character",
        back_populates="player",
        cascade="all, delete-orphan",
        foreign_keys="Character.player_id",
    )

    @classmethod
    def find_by_title(cls, title: str) -> "Player":
        """Find a player by title, return None if not found"""
        return cls.query.filter_by(title=title).first()

    def update_main_character(self):
        """
        Update the main character to be the one with the earliest join date.
        If no characters have join dates, use the first character.
        """
        if not self.characters:
            self.mainchar = None
            return

        # Get characters with join dates, sorted by join date
        chars_with_dates = [c for c in self.characters if c.joindate is not None]

        if chars_with_dates:
            # Sort by join date and take the earliest
            chars_with_dates.sort(key=lambda c: c.joindate)
            self.mainchar = chars_with_dates[0]
        else:
            # No join dates available, use the first character
            self.mainchar = self.characters[0]


class Character(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(nullable=True)
    joindate: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    player_id: Mapped[int] = mapped_column(db.ForeignKey("player.id"))
    player: Mapped["Player"] = db.relationship(
        "Player", back_populates="characters", foreign_keys=[player_id]
    )
    killmails: Mapped[list["Killmail"]] = db.relationship(
        "Killmail", back_populates="character"
    )

    @classmethod
    def find_or_create_by_name(
        cls, character_name: str, player_title: str = None
    ) -> "Character":
        """
        Find an existing character by name, or create a new one.
        If player_title is provided, associate the character with that player.
        """
        # First, try to find existing character by name
        character = cls.query.filter_by(name=character_name).first()

        if character:
            # Character exists, do not modify existing character's title or player association
            return character

        # Character doesn't exist, create new one
        # Try to get character info from API first
        from kmstat.api import api

        # First get character ID by name
        character_id = api.get_character_id_by_name(character_name)

        if character_id:
            # Character found in API, get full character data
            character = api.get_character(character_id)
            if not character:
                # Fallback if get_character fails but we have ID
                character = cls(id=character_id, name=character_name)
        else:
            # Character not found in API, report failure instead of creating
            from kmstat.upload_service import UploadError

            raise UploadError(
                f"Character '{character_name}' not found in EVE Online ESI"
            )

        # Associate with player - every character must have a player
        if player_title:
            # Determine the best title to use for player association
            final_player_title = player_title  # Default to imported title

            # If we got character from ESI and it has a title, prefer ESI title
            if hasattr(character, "title") and character.title:
                final_player_title = character.title

            # Try to find existing player by the final title
            player = Player.find_by_title(final_player_title)
            if not player:
                # If no player found with ESI title, also check with imported title
                if final_player_title != player_title:
                    player = Player.find_by_title(player_title)

                if not player:
                    # Create new player with the best available title
                    player = Player(title=final_player_title)
                    db.session.add(player)
                    db.session.flush()

            # Update character title to match the player title used
            character.title = final_player_title
            character.player = player

            # Add character to session before setting as main character
            db.session.add(character)
            db.session.flush()

            # Set as main character if player has no main character
            if not player.mainchar:
                player.mainchar = character
        else:
            # No player title provided, check if character has ESI title
            if hasattr(character, "title") and character.title:
                # Use ESI title as player title
                final_player_title = character.title

                # Try to find existing player
                player = Player.find_by_title(final_player_title)
                if not player:
                    # Create new player with ESI title
                    player = Player(title=final_player_title)
                    db.session.add(player)
                    db.session.flush()

                character.player = player

                # Add character to session before setting as main character
                db.session.add(character)
                db.session.flush()

                # Set as main character if player has no main character
                if not player.mainchar:
                    player.mainchar = character
            else:
                # No title available, associate with default "查无此人" player
                default_player = Player.query.filter_by(title="__查无此人__").first()
                if not default_player:
                    # Create the default player if it doesn't exist
                    default_player = Player(title="__查无此人__")
                    db.session.add(default_player)
                    db.session.flush()

                character.player = default_player
                # Add character to session
                db.session.add(character)
                db.session.flush()

        return character

    @classmethod
    def find_or_create_by_name_with_session(
        cls, character_name: str, player_title: str = None, session=None
    ) -> "Character":
        """
        Session-aware version of find_or_create_by_name for concurrent processing.
        Find an existing character by name, or create a new one.
        If player_title is provided, associate the character with that player.
        Uses the provided session instead of the default db.session.
        """
        if session is None:
            raise ValueError("Session is required for thread-safe operation")

        # First, try to find existing character by name
        character = session.query(cls).filter_by(name=character_name).first()

        if character:
            # Character exists, do not modify existing character's title or player association
            return character

        # Character doesn't exist, create new one
        # Try to get character info from API first
        from kmstat.api import api

        # First get character ID by name
        character_id = api.get_character_id_by_name(character_name)

        if character_id:
            # Character found in API, get full character data
            character = api.get_character(character_id)
            if not character:
                # Fallback if get_character fails but we have ID
                character = cls(id=character_id, name=character_name)
        else:
            # Character not found in API, report failure instead of creating
            from kmstat.upload_service import UploadError

            raise UploadError(
                f"Character '{character_name}' not found in EVE Online ESI"
            )

        # Associate with player - every character must have a player
        if player_title:
            # Determine the best title to use for player association
            final_player_title = player_title  # Default to imported title

            # If we got character from ESI and it has a title, prefer ESI title
            if hasattr(character, "title") and character.title:
                final_player_title = character.title

            # Try to find existing player by the final title using session
            player = session.query(Player).filter_by(title=final_player_title).first()
            if not player:
                # If no player found with ESI title, also check with imported title
                if final_player_title != player_title:
                    player = session.query(Player).filter_by(title=player_title).first()

                if not player:
                    # Create new player with the best available title
                    player = Player(title=final_player_title)
                    session.add(player)
                    session.flush()

            # Update character title to match the player title used
            character.title = final_player_title
            character.player = player

            # Add character to session before setting as main character
            session.add(character)
            session.flush()

            # Set as main character if player has no main character
            if not player.mainchar:
                player.mainchar = character
        else:
            # No player title provided, check if character has ESI title
            if hasattr(character, "title") and character.title:
                # Use ESI title as player title
                final_player_title = character.title

                # Try to find existing player using session
                player = (
                    session.query(Player).filter_by(title=final_player_title).first()
                )
                if not player:
                    # Create new player with ESI title
                    player = Player(title=final_player_title)
                    session.add(player)
                    session.flush()

                character.player = player

                # Add character to session before setting as main character
                session.add(character)
                session.flush()

                # Set as main character if player has no main character
                if not player.mainchar:
                    player.mainchar = character
            else:
                # No title available, associate with default "查无此人" player
                default_player = (
                    session.query(Player).filter_by(title="__查无此人__").first()
                )
                if not default_player:
                    # Create the default player if it doesn't exist
                    default_player = Player(title="__查无此人__")
                    session.add(default_player)
                    session.flush()

                character.player = default_player
                # Add character to session
                session.add(character)
                session.flush()

        return character

    def updatePlayer(self, title: str = None) -> bool:
        """
        Update the character's player based on title.
        If title is provided, use that to find or create a player.
        If title is not provided, use self.title if available.
        Will always create a new player if character has a title and no matching player exists.
        Also updates player join date to be the earliest of all associated characters.
        Returns True if successful, False if error occurred.
        """
        try:
            # If title is provided, update the character's title
            if title is not None:
                self.title = title

            if self.title is None:
                click.echo("Error: No title provided and character has no title")
                return False

            # Try to find existing player
            player = Player.find_by_title(self.title)

            # Always create player if none exists and we have a title
            if player is None:
                player = Player(title=self.title)
                # Set initial join date from this character if available
                if self.joindate:
                    player.joindate = self.joindate
                db.session.add(player)
                db.session.flush()  # Ensure player has an ID

                # Set this character as the main character for the new player
                player.mainchar = self
                click.echo(f"Info: Created new player {player.title}")

            # Ensure character is in session
            if self not in db.session:
                db.session.add(self)

            # Update relationship
            self.player = player

            # Update player join date to earliest among all associated characters
            self._update_player_join_date(player)

            # Update main character if this character has an earlier join date
            self._update_main_character(player)

            db.session.commit()
            return True

        except Exception as e:
            db.session.rollback()
            click.echo(f"Error: Error updating character: {str(e)}")
            return False

    def _update_player_join_date(self, player):
        """
        Update the player's join date to be the earliest among all associated characters.
        """
        # Get all characters for this player that have join dates
        characters_with_dates = [c for c in player.characters if c.joindate is not None]

        # Add the current character if it has a join date and isn't already in the list
        if self.joindate and self not in characters_with_dates:
            characters_with_dates.append(self)

        if characters_with_dates:
            # Find the earliest join date among all characters
            earliest_date = min(c.joindate for c in characters_with_dates)
            if player.joindate is None or earliest_date < player.joindate:
                player.joindate = earliest_date
                click.echo(
                    f"Info: Updated player {player.title} join date to {earliest_date}"
                )

    def _update_main_character(self, player):
        """
        Update the main character for the player.
        If no main character is set, or if this character has an earlier join date,
        set this character as the main character.
        """
        if player.mainchar is None:
            player.mainchar = self
            click.echo(f"Info: Set {self.name} as main character for {player.title}")
        elif self.joindate and player.mainchar.joindate:
            if self.joindate < player.mainchar.joindate:
                player.mainchar = self
                click.echo(
                    f"Info: Updated main character for {player.title} to {self.name} (earlier join date)"
                )
        elif self.joindate and not player.mainchar.joindate:
            # Current character has join date but main character doesn't
            player.mainchar = self
            click.echo(
                f"Info: Updated main character for {player.title} to {self.name} (has join date)"
            )


class SolarSystem(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)


class ItemType(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)


class Killmail(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    killmail_time: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    character_id: Mapped[int] = mapped_column(db.ForeignKey("character.id"))
    character: Mapped["Character"] = db.relationship("Character")
    solar_system_id: Mapped[int] = mapped_column(
        db.ForeignKey("solar_system.id"), nullable=False
    )
    solar_system: Mapped["SolarSystem"] = db.relationship("SolarSystem")
    victim_ship_type_id: Mapped[int] = mapped_column(
        db.ForeignKey("item_type.id"), nullable=False
    )
    victim_ship_type: Mapped["ItemType"] = db.relationship("ItemType")
    total_value: Mapped[float] = mapped_column(nullable=False)


class SystemState(db.Model):
    """Store system-wide state that needs to persist across application restarts."""

    key = db.Column(db.String(20), primary_key=True)
    date_value = db.Column(db.Date, nullable=True)

    @classmethod
    def get_latest_update(cls):
        """Get the latest update date, or None if not set"""
        from kmstat import app

        with app.app_context():
            state = cls.query.filter_by(key="latest_update").first()
            return state.date_value if state else None

    @classmethod
    def set_latest_update(cls, date_value):
        """Set the latest update date"""
        from kmstat import app

        with app.app_context():
            state = cls.query.filter_by(key="latest_update").first()
            if not state:
                state = cls(key="latest_update")
                db.session.add(state)
            state.date_value = date_value
            db.session.commit()

    @classmethod
    def get_sde_version(cls):
        """Get the SDE version date, or None if not set"""
        from kmstat import app

        with app.app_context():
            state = cls.query.filter_by(key="sde_version").first()
            return state.date_value if state else None

    @classmethod
    def set_sde_version(cls, date_value):
        """Set the SDE version date"""
        from kmstat import app

        with app.app_context():
            state = cls.query.filter_by(key="sde_version").first()
            if not state:
                state = cls(key="sde_version")
                db.session.add(state)
            state.date_value = date_value
            db.session.commit()


class MonthlyUpload(db.Model):
    """Store metadata for each monthly upload."""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(nullable=False)
    month: Mapped[int] = mapped_column(nullable=False)
    upload_date: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    tax_rate: Mapped[float] = mapped_column(
        nullable=False
    )  # Tax rate as decimal (e.g., 0.1 for 10%)
    ore_convert_rate: Mapped[float] = mapped_column(
        nullable=False
    )  # Ore conversion rate
    uploaded_by_id: Mapped[int] = mapped_column(
        db.ForeignKey("user.id"), nullable=False
    )
    uploaded_by: Mapped["User"] = db.relationship("User")

    # Relationships to the actual data
    pap_records: Mapped[list["PAPRecord"]] = db.relationship(
        "PAPRecord", back_populates="upload", cascade="all, delete-orphan"
    )
    bounty_records: Mapped[list["BountyRecord"]] = db.relationship(
        "BountyRecord", back_populates="upload", cascade="all, delete-orphan"
    )
    mining_records: Mapped[list["MiningRecord"]] = db.relationship(
        "MiningRecord", back_populates="upload", cascade="all, delete-orphan"
    )

    # Ensure unique year-month combination
    __table_args__ = (db.UniqueConstraint("year", "month", name="unique_year_month"),)

    def __repr__(self):
        return f"<MonthlyUpload {self.year}-{self.month:02d}>"


class PAPRecord(db.Model):
    """Store PAP (Player Activity Points) data."""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(
        db.ForeignKey("monthly_upload.id"), nullable=False
    )
    upload: Mapped["MonthlyUpload"] = db.relationship(
        "MonthlyUpload", back_populates="pap_records"
    )

    # Link to character (required - character must be created if not exists)
    character_id: Mapped[int] = mapped_column(
        db.ForeignKey("character.id"), nullable=False
    )
    character: Mapped["Character"] = db.relationship("Character")

    # Store original character name from Excel upload for error recovery
    raw_character_name: Mapped[str] = mapped_column(nullable=True)

    pap_points: Mapped[float] = mapped_column(nullable=False)
    strategic_pap_points: Mapped[float] = mapped_column(nullable=False)

    def __repr__(self):
        char_name = (
            self.character.name
            if self.character
            else self.raw_character_name or "Unknown"
        )
        return f"<PAPRecord {char_name}: {self.pap_points} PAP>"


class BountyRecord(db.Model):
    """Store bounty/tax data."""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(
        db.ForeignKey("monthly_upload.id"), nullable=False
    )
    upload: Mapped["MonthlyUpload"] = db.relationship(
        "MonthlyUpload", back_populates="bounty_records"
    )

    # Link to character (required - character must be created if not exists)
    character_id: Mapped[int] = mapped_column(
        db.ForeignKey("character.id"), nullable=False
    )
    character: Mapped["Character"] = db.relationship("Character")

    # Store original character name from Excel upload for error recovery
    raw_character_name: Mapped[str] = mapped_column(nullable=True)

    tax_isk: Mapped[float] = mapped_column(nullable=False)  # Tax amount in ISK

    def __repr__(self):
        char_name = (
            self.character.name
            if self.character
            else self.raw_character_name or "Unknown"
        )
        return f"<BountyRecord {char_name}: {self.tax_isk:,.0f} ISK>"


class MiningRecord(db.Model):
    """Store mining data."""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(
        db.ForeignKey("monthly_upload.id"), nullable=False
    )
    upload: Mapped["MonthlyUpload"] = db.relationship(
        "MonthlyUpload", back_populates="mining_records"
    )

    # Link to character (required - character must be created if not exists)
    character_id: Mapped[int] = mapped_column(
        db.ForeignKey("character.id"), nullable=False
    )
    character: Mapped["Character"] = db.relationship("Character")

    # Store original character name from Excel upload for error recovery
    raw_character_name: Mapped[str] = mapped_column(nullable=True)

    volume_m3: Mapped[float] = mapped_column(nullable=False)  # Volume in cubic meters

    def __repr__(self):
        char_name = (
            self.character.name
            if self.character
            else self.raw_character_name or "Unknown"
        )
        return f"<MiningRecord {char_name}: {self.volume_m3:,.1f} m³>"
