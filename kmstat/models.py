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
    characters: Mapped[list["Character"]] = db.relationship(
        "Character", back_populates="player", cascade="all, delete-orphan"
    )

    @classmethod
    def find_by_title(cls, title: str) -> "Player":
        """Find a player by title, return None if not found"""
        return cls.query.filter_by(title=title).first()


class Character(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(nullable=True)
    joindate: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    player_id: Mapped[int] = mapped_column(db.ForeignKey("player.id"))
    player: Mapped["Player"] = db.relationship("Player", back_populates="characters")
    killmails: Mapped[list["Killmail"]] = db.relationship(
        "Killmail", back_populates="character"
    )

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
                click.echo(f"Info: Created new player {player.title}")

            # Ensure character is in session
            if self not in db.session:
                db.session.add(self)

            # Update relationship
            self.player = player

            # Update player join date to earliest among all associated characters
            self._update_player_join_date(player)

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
