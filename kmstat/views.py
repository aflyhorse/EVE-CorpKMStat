from datetime import datetime
from flask import render_template, request
from sqlalchemy import func
from kmstat import app, db
from kmstat.models import Player, Character, Killmail
from kmstat.config import config
from kmstat.utils import get_last_day_of_month


@app.route("/")
@app.route("/dashboard")
def dashboard():
    current_year = datetime.now().year
    current_month = datetime.now().month
    start_year = config.startupdate.year

    # Get year from query params, default to current year
    try:
        selected_year = int(request.args.get("year", current_year))
    except (TypeError, ValueError):
        selected_year = current_year

    # Get month and ensure it's an integer between 1-12
    try:
        selected_month = int(request.args.get("month", current_month))
        selected_month = max(1, min(12, selected_month))
    except (TypeError, ValueError):
        selected_month = current_month

    # Query for yearly stats using character.killmails relationship
    year_stats = (
        db.session.query(
            Character.player_id,
            Player.title.label("name"),
            Player.id.label("player_id"),
            func.sum(Killmail.total_value).label("total_value"),
        )
        .join(Character.player)
        .join(Character.killmails)
        .filter(func.strftime("%Y", Killmail.killmail_time) == str(selected_year))
        .group_by(Character.player_id)
        .order_by(func.sum(Killmail.total_value).desc())
        .all()
    )

    # Query for monthly stats using character.killmails relationship
    month_stats = (
        db.session.query(
            Character.player_id,
            Player.title.label("name"),
            Player.id.label("player_id"),
            func.sum(Killmail.total_value).label("total_value"),
        )
        .join(Character.player)
        .join(Character.killmails)
        .filter(
            func.strftime("%Y", Killmail.killmail_time) == str(selected_year),
            func.strftime("%m", Killmail.killmail_time) == f"{selected_month:02d}",
        )
        .group_by(Character.player_id)
        .order_by(func.sum(Killmail.total_value).desc())
        .all()
    )

    # Prepare data for template
    year_stats = [(i + 1, stat) for i, stat in enumerate(year_stats)]
    month_stats = [(i + 1, stat) for i, stat in enumerate(month_stats)]

    return render_template(
        "dashboard.html.jinja2",
        years=range(start_year, current_year + 1),
        current_year=current_year,
        current_month=current_month,
        selected_year=selected_year,
        selected_month=selected_month,
        year_stats=year_stats,
        month_stats=month_stats,
        config=config,
    )


@app.route("/search-player")
def search_player():
    # Get all players for the dropdown
    players = Player.query.order_by(Player.title).all()

    # Get search parameters
    player_id = request.args.get("player_id", type=int)
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    # Validate and fix end_date if it's invalid
    if end_date:
        try:
            date_parts = end_date.split("-")
            year = int(date_parts[0])
            month = int(date_parts[1])
            day = int(date_parts[2])

            # Get the actual last day of the month
            last_day = get_last_day_of_month(year, month)

            # If the day is invalid, use the last day of the month
            if day > last_day:
                end_date = f"{year}-{month:02d}-{last_day:02d}"
        except (ValueError, IndexError):
            # If date parsing fails, don't modify the end_date
            pass

    kills = []
    player_characters = []
    selected_player_name = None

    if player_id:
        selected_player = Player.query.get(player_id)
        if selected_player:
            selected_player_name = selected_player.title
            # Get player's characters with killmails loaded
            player_characters = (
                Character.query.options(db.joinedload(Character.killmails))
                .filter(Character.player_id == player_id)
                .order_by(Character.name)
                .all()
            )

            # Get killmails from all player's characters using the relationship
            query = Killmail.query.join(Character).filter(
                Character.player_id == player_id
            )

            # Add date filters if provided
            if start_date:
                query = query.filter(Killmail.killmail_time >= start_date)
            if end_date:
                query = query.filter(Killmail.killmail_time <= f"{end_date} 23:59:59")

            kills = query.order_by(Killmail.id.desc()).all()

    return render_template(
        "search_player.html.jinja2",
        players=players,
        selected_player=player_id,
        selected_player_name=selected_player_name,
        start_date=start_date,
        end_date=end_date,
        kills=kills,
        player_characters=player_characters,
        config=config,
    )


@app.route("/search-char")
def search_char():
    # Get all characters for the dropdown
    characters = Character.query.order_by(func.lower(Character.name)).all()

    # Get search parameters
    character_id = request.args.get("character", type=int)
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    kills = []
    if character_id:
        # Get character with killmails loaded
        character = Character.query.options(db.joinedload(Character.killmails)).get(
            character_id
        )
        if character:
            # Filter killmails using the relationship
            query = Killmail.query.filter(Killmail.character_id == character_id)

            # Add date filters if provided
            if start_date:
                query = query.filter(Killmail.killmail_time >= start_date)
            if end_date:
                query = query.filter(Killmail.killmail_time <= f"{end_date} 23:59:59")

            kills = query.order_by(Killmail.id.desc()).all()

    return render_template(
        "search_char.html.jinja2",
        characters=characters,
        selected_character=character_id,
        start_date=start_date,
        end_date=end_date,
        kills=kills,
        config=config,
    )


@app.route("/character-claim")
def character_claim():
    # Get the first player's characters
    first_player = Player.query.first()
    characters = (
        Character.query.filter_by(player_id=first_player.id).all()
        if first_player
        else []
    )

    return render_template(
        "character_claim.html.jinja2", characters=characters, config=config
    )


@app.route("/help")
def help_page():
    return render_template(
        "help.html.jinja2",
        config=config,
    )
