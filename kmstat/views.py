from datetime import datetime
from flask import render_template, request, jsonify, send_file
from flask_login import login_required, current_user
from sqlalchemy import func
from kmstat import app, db
from kmstat.models import Player, Character, Killmail
from kmstat.config import config
from kmstat.utils import get_last_day_of_month
import os
from werkzeug.utils import secure_filename
from kmstat.upload_service import MonthlyUploadService, UploadError
from kmstat.models import MonthlyUpload


def has_unclaimed_characters():
    """Check if there are any unclaimed characters (associated with __查无此人__)"""
    default_player = Player.query.filter_by(title="__查无此人__").first()
    if not default_player:
        return False

    # Check if any characters are associated with the default player
    unclaimed_count = Character.query.filter_by(player_id=default_player.id).count()
    return unclaimed_count > 0


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
    # Get all players with at least one character for the dropdown
    players = (
        Player.query.join(Character, Player.id == Character.player_id)
        .group_by(Player.id)
        .having(func.count(Character.id) > 0)
        .order_by(Player.title)
        .all()
    )

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
    selected_player_obj = None

    if player_id:
        selected_player_obj = Player.query.get(player_id)
        if selected_player_obj:
            selected_player_name = selected_player_obj.title
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
        selected_player_obj=selected_player_obj,
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
    selected_character = None
    if character_id:
        # Get character with killmails loaded
        selected_character = Character.query.options(
            db.joinedload(Character.killmails)
        ).get(character_id)
        if selected_character:
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
        character_obj=selected_character,  # Pass the character object to the template
        start_date=start_date,
        end_date=end_date,
        kills=kills,
        config=config,
    )


@app.route("/character-claim")
def character_claim():
    # Get characters that are associated with the default "__查无此人__" player
    # These are characters that need proper player association
    default_player = Player.query.filter_by(title="__查无此人__").first()
    characters = (
        Character.query.filter_by(player_id=default_player.id).all()
        if default_player
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


@app.route("/associate-character/<int:character_id>", methods=["GET", "POST"])
@login_required
def associate_character(character_id):
    """Associate a character with a player (iframe view)."""
    character = Character.query.get_or_404(character_id)

    if request.method == "POST":
        player_id = request.form.get("player_id")
        new_player_title = request.form.get("new_player_title")

        try:
            if player_id:
                # Associate with existing player
                player = Player.query.get(player_id)
                if not player:
                    return jsonify({"success": False, "message": "选择的玩家不存在"})

                # Use updatePlayer method to properly handle join dates
                if character.updatePlayer(player.title):
                    return jsonify(
                        {
                            "success": True,
                            "message": f"角色 {character.name} 已关联到玩家 {player.title}",
                        }
                    )
                else:
                    return jsonify({"success": False, "message": "关联失败"})

            elif new_player_title:
                # Create new player and associate
                new_player_title = new_player_title.strip()
                if not new_player_title:
                    return jsonify({"success": False, "message": "玩家头衔不能为空"})

                # Check if player with this title already exists
                existing_player = Player.query.filter_by(title=new_player_title).first()
                if existing_player:
                    return jsonify({"success": False, "message": "该头衔的玩家已存在"})

                # Use updatePlayer method to create new player and associate
                if character.updatePlayer(new_player_title):
                    return jsonify(
                        {
                            "success": True,
                            "message": f"已创建新玩家 {new_player_title} 并关联角色 {character.name}",
                        }
                    )
                else:
                    return jsonify({"success": False, "message": "创建玩家失败"})
            else:
                return jsonify(
                    {"success": False, "message": "请选择现有玩家或输入新玩家头衔"}
                )

        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": f"关联失败: {str(e)}"})

    # GET request - show the form
    # Get all players except the default "__查无此人__" player
    players = (
        Player.query.filter(Player.title != "__查无此人__").order_by(Player.title).all()
    )

    return render_template(
        "associate_character.html.jinja2", character=character, players=players
    )


@app.route("/set-main-character/<int:character_id>", methods=["POST"])
@login_required
def set_main_character(character_id):
    """Set a character as the main character for their player."""
    try:
        character = Character.query.get_or_404(character_id)

        if not character.player:
            return jsonify({"success": False, "message": "角色未关联到任何玩家"})

        # Update the player's main character
        character.player.mainchar = character
        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": f"已将 {character.name} 设为 {character.player.title} 的主角色",
            }
        )

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"设置失败: {str(e)}"})


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload_monthly_data():
    """Upload monthly data from Excel file."""
    if request.method == "GET":
        # Calculate default year and month (last month)
        from datetime import datetime

        current_date = datetime.now()
        if current_date.month == 1:
            # If current month is January, last month is December of previous year
            default_year = current_date.year - 1
            default_month = 12
        else:
            # Otherwise, just subtract 1 from current month
            default_year = current_date.year
            default_month = current_date.month - 1

        # Get default tax rate and ore convert rate from last upload
        last_upload = MonthlyUpload.query.order_by(
            MonthlyUpload.year.desc(), MonthlyUpload.month.desc()
        ).first()

        default_tax_rate = last_upload.tax_rate if last_upload else 0.1
        default_ore_convert_rate = (
            last_upload.ore_convert_rate if last_upload else 300.0
        )

        # Show upload form with existing uploads
        uploads = MonthlyUpload.query.order_by(
            MonthlyUpload.year.desc(), MonthlyUpload.month.desc()
        ).all()

        # Check for unclaimed characters
        has_unclaimed = has_unclaimed_characters()

        return render_template(
            "upload.html.jinja2",
            uploads=uploads,
            default_year=default_year,
            default_month=default_month,
            default_tax_rate=default_tax_rate,
            default_ore_convert_rate=default_ore_convert_rate,
            has_unclaimed=has_unclaimed,
        )

    # Handle POST request
    try:
        # Validate form data
        if "file" not in request.files:
            return jsonify({"success": False, "message": "没有选择文件"})

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"success": False, "message": "没有选择文件"})

        if not file.filename.endswith((".xlsx", ".xls")):
            return jsonify(
                {"success": False, "message": "文件格式必须是Excel (.xlsx或.xls)"}
            )

        year = request.form.get("year", type=int)
        month = request.form.get("month", type=int)
        tax_rate = request.form.get("tax_rate", type=float)
        ore_convert_rate = request.form.get("ore_convert_rate", type=float)
        overwrite = request.form.get("overwrite") == "true"

        if not all([year, month, tax_rate is not None, ore_convert_rate is not None]):
            return jsonify({"success": False, "message": "请填写所有必需字段"})

        if not (1 <= month <= 12):
            return jsonify({"success": False, "message": "月份必须在1-12之间"})

        if tax_rate < 0 or tax_rate > 1:
            return jsonify({"success": False, "message": "税率必须在0-1之间"})

        # Save uploaded file temporarily
        filename = secure_filename(file.filename)
        temp_path = os.path.join(app.instance_path, "temp", filename)
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        file.save(temp_path)

        try:
            # Process the upload
            upload = MonthlyUploadService.process_excel_upload(
                temp_path,
                year,
                month,
                tax_rate,
                ore_convert_rate,
                current_user,
                overwrite,
            )

            summary = MonthlyUploadService.get_upload_summary(upload)

            # Check for unclaimed characters after upload
            has_unclaimed = has_unclaimed_characters()

            return jsonify(
                {
                    "success": True,
                    "message": f"成功上传 {year}-{month:02d} 数据",
                    "summary": summary,
                    "has_unclaimed": has_unclaimed,
                }
            )

        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except UploadError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception as e:
        return jsonify({"success": False, "message": f"上传失败: {str(e)}"})


@app.route("/upload/<int:year>/<int:month>", methods=["DELETE"])
@login_required
def delete_monthly_data(year, month):
    """Delete monthly data."""
    try:
        if MonthlyUploadService.delete_upload(year, month):
            return jsonify(
                {"success": True, "message": f"已删除 {year}-{month:02d} 数据"}
            )
        else:
            return jsonify({"success": False, "message": "数据不存在"})
    except Exception as e:
        return jsonify({"success": False, "message": f"删除失败: {str(e)}"})


@app.route("/upload/<int:year>/<int:month>/summary")
def view_upload_summary(year, month):
    """View summary of uploaded data."""
    upload = MonthlyUpload.query.filter_by(year=year, month=month).first_or_404()
    summary = MonthlyUploadService.get_upload_summary(upload)
    return render_template("upload_summary.html.jinja2", upload=upload, summary=summary)


@app.route("/download-template")
@login_required
def download_template():
    """Generate and download Excel template file."""
    import pandas as pd
    from io import BytesIO

    # Create empty template data with only column headers
    pap_data = {
        "名字": [],
        "Title": [],
        "PAP": [],
        "战略PAP": [],
    }

    bounty_data = {
        "名字": [],
        "纳税(isk)": [],
    }

    mining_data = {
        "名字": [],
        "主人物": [],
        "体积(m3)": [],
    }

    # Create DataFrames
    pap_df = pd.DataFrame(pap_data)
    bounty_df = pd.DataFrame(bounty_data)
    mining_df = pd.DataFrame(mining_data)

    # Create Excel file in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pap_df.to_excel(writer, sheet_name="PAP", index=False)
        bounty_df.to_excel(writer, sheet_name="赏金", index=False)
        mining_df.to_excel(writer, sheet_name="挖矿", index=False)

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="monthly_data_template.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/upload/check-exists/<int:year>/<int:month>")
@login_required
def check_upload_exists(year, month):
    """Check if upload data exists for the given year and month."""
    exists = MonthlyUploadService.upload_exists(year, month)
    return jsonify({"exists": exists})
