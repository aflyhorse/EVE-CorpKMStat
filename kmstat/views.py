from datetime import datetime
from flask import render_template, request
from sqlalchemy import func
from kmstat import app, db
from kmstat.models import Player, Character, Killmail
from kmstat.config import config


@app.route('/')
@app.route('/dashboard')
def dashboard():
    current_year = datetime.now().year
    current_month = datetime.now().month
    start_year = config.startupdate.year
    
    # Get year from query params, default to current year
    try:
        selected_year = int(request.args.get('year', current_year))
    except (TypeError, ValueError):
        selected_year = current_year

    # Get month and ensure it's an integer between 1-12
    try:
        selected_month = int(request.args.get('month', current_month))
        selected_month = max(1, min(12, selected_month))
    except (TypeError, ValueError):
        selected_month = current_month
    
    # Query for yearly stats
    year_stats = db.session.query(
        Character.player_id,
        Player.title.label('name'),
        func.sum(Killmail.total_value).label('total_value')
    ).join(
        Character.player
    ).join(
        Killmail, Killmail.character_id == Character.id
    ).filter(
        func.strftime('%Y', Killmail.killmail_time) == str(selected_year)
    ).group_by(
        Character.player_id
    ).order_by(
        func.sum(Killmail.total_value).desc()
    ).all()
    
    # Query for monthly stats (for selected year and month)
    month_stats = db.session.query(
        Character.player_id,
        Player.title.label('name'),
        func.sum(Killmail.total_value).label('total_value')
    ).join(
        Character.player
    ).join(
        Killmail, Killmail.character_id == Character.id
    ).filter(
        func.strftime('%Y', Killmail.killmail_time) == str(selected_year),
        func.strftime('%m', Killmail.killmail_time) == f"{selected_month:02d}"
    ).group_by(
        Character.player_id
    ).order_by(
        func.sum(Killmail.total_value).desc()
    ).all()
    
    # Prepare data for template
    year_stats = [(i+1, stat) for i, stat in enumerate(year_stats)]
    month_stats = [(i+1, stat) for i, stat in enumerate(month_stats)]
    
    return render_template(
        'dashboard.html',
        years=range(start_year, current_year + 1),
        current_year=current_year,
        current_month=current_month,
        selected_year=selected_year,
        selected_month=selected_month,
        year_stats=year_stats,
        month_stats=month_stats,
        config=config
    )


@app.route('/detailed-search')
def detailed_search():
    return render_template('detailed_search.html', config=config)


@app.route('/character-claim')
def character_claim():
    # Get the first player's characters
    first_player = Player.query.first()
    characters = Character.query.filter_by(player_id=first_player.id).all() if first_player else []
    
    return render_template('character_claim.html', characters=characters, config=config)
