"""
Database models for the application.
"""

from kmstat import db
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime
import click


class Player(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(nullable=False, unique=True)
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
    player_id: Mapped[int] = mapped_column(db.ForeignKey("player.id"))
    player: Mapped["Player"] = db.relationship("Player", back_populates="characters")
    killmails: Mapped[list["Killmail"]] = db.relationship(
        "Killmail", back_populates="character"
    )

    def updatePlayer(self, title: str = None, force_create: bool = False) -> bool:
        """
        Update the character's player based on title.
        If title is provided, use that to find player.
        If title is not provided, use self.title if available.
        If force_create is True, create a new player if one doesn't exist.
        Returns True if successful, False if error occurred or player not found.
        """
        try:
            search_title = title if title is not None else self.title

            if search_title is None:
                click.echo("Error: No title provided and character has no title")
                return False

            # Try to find existing player
            player = Player.find_by_title(search_title)

            if player is None:
                if force_create:
                    player = Player(title=search_title)
                    db.session.add(player)
                else:
                    click.echo(f"Error: No player found with title '{search_title}'")
                    return False

            # Ensure character is in session
            if self not in db.session:
                db.session.add(self)

            # Update relationship
            self.player = player
            db.session.commit()
            return True

        except Exception as e:
            db.session.rollback()
            click.echo(f"Error updating player: {str(e)}")
            return False


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
