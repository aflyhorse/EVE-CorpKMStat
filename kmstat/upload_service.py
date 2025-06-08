"""
Service for handling monthly Excel file uploads.
"""

import pandas as pd
import os
from datetime import datetime
from flask import current_app
from kmstat import db
from concurrent.futures import ThreadPoolExecutor, as_completed
from kmstat.models import (
    MonthlyUpload,
    PAPRecord,
    BountyRecord,
    MiningRecord,
    Character,
    User,
)


class UploadError(Exception):
    """Custom exception for upload errors."""

    pass


class MonthlyUploadService:
    """Service for processing monthly Excel uploads."""

    @staticmethod
    def process_excel_upload(
        file_path: str,
        year: int,
        month: int,
        tax_rate: float,
        ore_convert_rate: float,
        uploaded_by: User,
        overwrite: bool = False,
    ) -> MonthlyUpload:
        """
        Process an Excel file upload and store the data in the database.

        Args:
            file_path: Path to the Excel file
            year: Year of the data
            month: Month of the data (1-12)
            tax_rate: Tax rate as decimal (e.g., 0.1 for 10%)
            ore_convert_rate: Ore conversion rate
            uploaded_by: User who uploaded the file
            overwrite: Whether to overwrite existing data

        Returns:
            MonthlyUpload: The created upload record

        Raises:
            UploadError: If there are validation or processing errors
        """

        # Check if upload already exists for this year/month
        existing = MonthlyUpload.query.filter_by(year=year, month=month).first()
        if existing and not overwrite:
            raise UploadError(f"Data for {year}-{month:02d} already exists")

        try:
            current_app.logger.info(f"Starting Excel file processing: {file_path}")
            current_app.logger.info(f"File size: {os.path.getsize(file_path)} bytes")

            # If overwriting, delete existing data first
            if existing and overwrite:
                current_app.logger.info(
                    f"Deleting existing data for {year}-{month:02d}"
                )
                MonthlyUploadService.delete_upload(year, month)

            # Read Excel file
            current_app.logger.info("Reading Excel file...")
            excel_data = pd.read_excel(file_path, sheet_name=None)
            current_app.logger.info(f"Excel sheets found: {list(excel_data.keys())}")

            # Validate required sheets
            required_sheets = ["PAP", "赏金", "挖矿"]
            missing_sheets = [
                sheet for sheet in required_sheets if sheet not in excel_data
            ]
            if missing_sheets:
                raise UploadError(
                    f"Missing required sheets: {', '.join(missing_sheets)}"
                )

            current_app.logger.info(
                "All required sheets found, proceeding with data processing"
            )

            # Create upload record
            current_app.logger.info("Creating upload record...")
            upload = MonthlyUpload(
                year=year,
                month=month,
                upload_date=datetime.now(),
                tax_rate=tax_rate,
                ore_convert_rate=ore_convert_rate,
                uploaded_by=uploaded_by,
            )
            db.session.add(upload)
            db.session.flush()  # Get the ID
            current_app.logger.info(f"Upload record created with ID: {upload.id}")

            # Commit the upload record so it's visible to other sessions/threads
            db.session.commit()
            current_app.logger.info("Upload record committed to database")

            # Process each sheet concurrently
            current_app.logger.info("Starting concurrent sheet processing...")

            try:
                # Get the current Flask app instance to pass to threads
                app_instance = current_app._get_current_object()

                def process_sheet_with_session(sheet_name, sheet_data, upload_id):
                    """Process a sheet in a separate thread with its own database session."""
                    thread_session = None
                    try:
                        # Push a new application context for this thread
                        with app_instance.app_context():
                            # Import within the context to ensure proper setup
                            from sqlalchemy.orm import sessionmaker
                            from kmstat import db as main_db
                            from flask import current_app as thread_app

                            # Create a new session bound to the same engine
                            Session = sessionmaker(bind=main_db.engine)
                            thread_session = Session()

                            # Get the upload object in this thread's session
                            thread_upload = thread_session.query(MonthlyUpload).get(
                                upload_id
                            )
                            if not thread_upload:
                                raise UploadError(
                                    f"Upload record not found for ID {upload_id}"
                                )

                            # Log within the app context
                            thread_app.logger.info(
                                f"Processing {sheet_name} sheet in thread..."
                            )

                            # Process the sheet with the thread's session
                            if sheet_name == "PAP":
                                count = MonthlyUploadService._process_pap_sheet_with_session(
                                    sheet_data, thread_upload, thread_session
                                )
                            elif sheet_name == "赏金":
                                count = MonthlyUploadService._process_bounty_sheet_with_session(
                                    sheet_data, thread_upload, thread_session
                                )
                            elif sheet_name == "挖矿":
                                count = MonthlyUploadService._process_mining_sheet_with_session(
                                    sheet_data, thread_upload, thread_session
                                )
                            else:
                                raise UploadError(f"Unknown sheet type: {sheet_name}")

                            # Commit this thread's session
                            thread_session.commit()
                            thread_app.logger.info(
                                f"{sheet_name} sheet processed: {count} records"
                            )

                            return sheet_name, count

                    except Exception as e:
                        if thread_session:
                            try:
                                thread_session.rollback()
                            except:
                                pass

                        # Log the error - try different approaches for logging
                        error_msg = f"Error processing {sheet_name} sheet: {str(e)}"
                        try:
                            # Try to use app context logging
                            with app_instance.app_context():
                                from flask import current_app as thread_app

                                thread_app.logger.error(error_msg, exc_info=True)
                        except:
                            # Fallback to stderr if logging fails
                            import sys

                            print(error_msg, file=sys.stderr)

                        raise UploadError(error_msg)
                    finally:
                        if thread_session:
                            try:
                                thread_session.close()
                            except:
                                pass

                # Use ThreadPoolExecutor to process sheets concurrently
                with ThreadPoolExecutor(max_workers=3) as executor:
                    # Submit all sheet processing tasks
                    future_to_sheet = {
                        executor.submit(
                            process_sheet_with_session,
                            "PAP",
                            excel_data["PAP"],
                            upload.id,
                        ): "PAP",
                        executor.submit(
                            process_sheet_with_session,
                            "赏金",
                            excel_data["赏金"],
                            upload.id,
                        ): "赏金",
                        executor.submit(
                            process_sheet_with_session,
                            "挖矿",
                            excel_data["挖矿"],
                            upload.id,
                        ): "挖矿",
                    }

                    # Collect results as they complete
                    pap_count = bounty_count = mining_count = 0
                    for future in as_completed(future_to_sheet):
                        sheet_type = future_to_sheet[future]
                        try:
                            sheet_name, count = future.result()
                            if sheet_name == "PAP":
                                pap_count = count
                            elif sheet_name == "赏金":
                                bounty_count = count
                            elif sheet_name == "挖矿":
                                mining_count = count
                        except Exception as e:
                            current_app.logger.error(
                                f"Sheet processing failed for {sheet_type}: {str(e)}"
                            )
                            raise e

                current_app.logger.info(
                    "All sheets processed successfully with concurrent processing"
                )

            except Exception as e:
                current_app.logger.warning(
                    f"Concurrent processing failed: {str(e)}, falling back to sequential processing"
                )

                # Fallback to sequential processing
                current_app.logger.info("Processing PAP sheet (sequential fallback)...")
                pap_count = MonthlyUploadService._process_pap_sheet(
                    excel_data["PAP"], upload
                )
                current_app.logger.info(f"PAP sheet processed: {pap_count} records")

                current_app.logger.info(
                    "Processing bounty sheet (sequential fallback)..."
                )
                bounty_count = MonthlyUploadService._process_bounty_sheet(
                    excel_data["赏金"], upload
                )
                current_app.logger.info(
                    f"Bounty sheet processed: {bounty_count} records"
                )

                current_app.logger.info(
                    "Processing mining sheet (sequential fallback)..."
                )
                mining_count = MonthlyUploadService._process_mining_sheet(
                    excel_data["挖矿"], upload
                )
                current_app.logger.info(
                    f"Mining sheet processed: {mining_count} records"
                )

                current_app.logger.info(
                    "All sheets processed successfully with sequential fallback"
                )

            # Commit the main transaction (upload record already created)
            current_app.logger.info("Committing main database transaction...")
            # The individual sheet transactions were already committed in their threads
            # We just need to refresh the upload object to see the related records
            db.session.refresh(upload)

            current_app.logger.info(
                f"Successfully uploaded {year}-{month:02d}: "
                f"{pap_count} PAP records, {bounty_count} bounty records, "
                f"{mining_count} mining records"
            )

            return upload

        except Exception as e:
            current_app.logger.error(
                f"Error during upload processing: {str(e)}", exc_info=True
            )
            # Since we committed the upload early, we need to clean it up on error
            try:
                # Remove the upload record and any related records that might have been created
                db.session.delete(upload)
                db.session.commit()
                current_app.logger.info(
                    "Cleaned up upload record due to processing error"
                )
            except Exception as cleanup_error:
                current_app.logger.error(
                    f"Error cleaning up upload record: {cleanup_error}"
                )
                db.session.rollback()

            if isinstance(e, UploadError):
                raise
            else:
                raise UploadError(f"Error processing file: {str(e)}")

    @staticmethod
    def _process_pap_sheet(df: pd.DataFrame, upload: MonthlyUpload) -> int:
        """Process PAP sheet data."""
        if df.empty:
            return 0

        # Validate columns
        expected_cols = ["名字", "Title", "PAP", "战略PAP"]
        missing_cols = [col for col in expected_cols if col not in df.columns]
        if missing_cols:
            raise UploadError(f"PAP sheet missing columns: {', '.join(missing_cols)}")

        count = 0
        for _, row in df.iterrows():
            # Skip rows with missing essential data
            if pd.isna(row["名字"]) or pd.isna(row["Title"]):
                continue

            character_name = str(row["名字"]).strip()
            player_title = str(row["Title"]).strip()
            pap_points = float(row["PAP"]) if not pd.isna(row["PAP"]) else 0.0
            strategic_pap = (
                float(row["战略PAP"]) if not pd.isna(row["战略PAP"]) else 0.0
            )

            # Find or create character with player association (no API calls)
            character = (
                db.session.query(Character).filter_by(name=character_name).first()
            )
            if not character:
                # Character doesn't exist - create minimal character without API calls
                from kmstat.models import Player

                # Find or create player
                player = db.session.query(Player).filter_by(title=player_title).first()
                if not player:
                    player = Player(title=player_title)
                    db.session.add(player)
                    db.session.flush()

                # Create character with minimal info (no API call or ESI validation)
                character = Character(
                    name=character_name, title=player_title, player=player
                )
                db.session.add(character)
                db.session.flush()

            pap_record = PAPRecord(
                upload=upload,
                character=character,
                pap_points=pap_points,
                strategic_pap_points=strategic_pap,
            )
            db.session.add(pap_record)
            count += 1

        return count

    @staticmethod
    def _process_bounty_sheet(df: pd.DataFrame, upload: MonthlyUpload) -> int:
        """Process bounty sheet data."""
        if df.empty:
            return 0

        # Validate columns
        expected_cols = ["名字", "纳税(isk)"]
        missing_cols = [col for col in expected_cols if col not in df.columns]
        if missing_cols:
            raise UploadError(
                f"Bounty sheet missing columns: {', '.join(missing_cols)}"
            )

        count = 0
        for _, row in df.iterrows():
            # Skip rows with missing essential data
            if pd.isna(row["名字"]) or pd.isna(row["纳税(isk)"]):
                continue

            character_name = str(row["名字"]).strip()
            tax_isk = float(row["纳税(isk)"])

            # Find or create character (no player title provided in bounty sheet, no API calls)
            character = (
                db.session.query(Character).filter_by(name=character_name).first()
            )
            if not character:
                # Character doesn't exist - create minimal character without API calls
                from kmstat.models import Player

                # Associate with default player
                default_player = (
                    db.session.query(Player).filter_by(title="__查无此人__").first()
                )
                if not default_player:
                    default_player = Player(title="__查无此人__")
                    db.session.add(default_player)
                    db.session.flush()

                # Create character with minimal info (no API call)
                character = Character(name=character_name, player=default_player)
                db.session.add(character)
                db.session.flush()

            bounty_record = BountyRecord(
                upload=upload, character=character, tax_isk=tax_isk
            )
            db.session.add(bounty_record)
            count += 1

        return count

    @staticmethod
    def _process_mining_sheet(df: pd.DataFrame, upload: MonthlyUpload) -> int:
        """Process mining sheet data."""
        if df.empty:
            return 0

        # Validate columns
        expected_cols = ["名字", "主人物", "体积(m3)"]
        missing_cols = [col for col in expected_cols if col not in df.columns]
        if missing_cols:
            raise UploadError(
                f"Mining sheet missing columns: {', '.join(missing_cols)}"
            )

        count = 0
        for _, row in df.iterrows():
            # Skip rows with missing essential data
            if pd.isna(row["名字"]) or pd.isna(row["体积(m3)"]):
                continue

            character_name = str(row["名字"]).strip()
            main_character_name = (
                str(row["主人物"]).strip() if not pd.isna(row["主人物"]) else ""
            )
            volume_m3 = float(row["体积(m3)"])

            # Handle character association with player based on main character (no API calls)
            character = (
                db.session.query(Character).filter_by(name=character_name).first()
            )
            if not character:
                # Character doesn't exist - create minimal character without API calls
                from kmstat.models import Player

                player = None
                if main_character_name:
                    # Try to find the main character to get the player title
                    main_char = (
                        db.session.query(Character)
                        .filter_by(name=main_character_name)
                        .first()
                    )
                    if main_char and main_char.player:
                        # Associate with the same player as the main character
                        player = main_char.player

                if not player:
                    # No main character or player found, use default
                    player = (
                        db.session.query(Player).filter_by(title="__查无此人__").first()
                    )
                    if not player:
                        player = Player(title="__查无此人__")
                        db.session.add(player)
                        db.session.flush()

                # Create character with minimal info (no API call)
                character = Character(name=character_name, player=player)
                db.session.add(character)
                db.session.flush()

            mining_record = MiningRecord(
                upload=upload, character=character, volume_m3=volume_m3
            )
            db.session.add(mining_record)
            count += 1

        return count

    @staticmethod
    def get_upload_summary(upload: MonthlyUpload) -> dict:
        """Get a summary of an upload."""
        # Aggregate data by player
        player_data = {}

        # Process PAP records
        for pap_record in upload.pap_records:
            character = pap_record.character
            if character and character.player:
                player_title = character.player.title
                player_id = character.player.id
                main_character = (
                    character.player.mainchar.name
                    if character.player.mainchar
                    else None
                )
            else:
                player_title = pap_record.player_title or "__查无此人__"
                # Find the default player ID
                from kmstat.models import Player

                default_player = Player.query.filter_by(title="__查无此人__").first()
                player_id = default_player.id if default_player else None
                main_character = None

            if player_title not in player_data:
                player_data[player_title] = {
                    "player_title": player_title,
                    "player_id": player_id,
                    "main_character": main_character,
                    "total_tax": 0.0,
                    "total_mining_volume": 0.0,
                    "total_pap": 0.0,
                    "strategic_pap": 0.0,
                    "total_income": 0.0,
                    "status": "",
                }

            player_data[player_title]["total_pap"] += pap_record.pap_points
            player_data[player_title][
                "strategic_pap"
            ] += pap_record.strategic_pap_points

            # Update main character if we have one and haven't set it yet
            if main_character and not player_data[player_title]["main_character"]:
                player_data[player_title]["main_character"] = main_character

        # Process bounty records
        for bounty_record in upload.bounty_records:
            character = bounty_record.character
            if character and character.player:
                player_title = character.player.title
                player_id = character.player.id
                main_character = (
                    character.player.mainchar.name
                    if character.player.mainchar
                    else None
                )
            else:
                player_title = "__查无此人__"
                # Find the default player ID
                from kmstat.models import Player

                default_player = Player.query.filter_by(title="__查无此人__").first()
                player_id = default_player.id if default_player else None
                main_character = None

            if player_title not in player_data:
                player_data[player_title] = {
                    "player_title": player_title,
                    "player_id": player_id,
                    "main_character": main_character,
                    "total_tax": 0.0,
                    "total_mining_volume": 0.0,
                    "total_pap": 0.0,
                    "strategic_pap": 0.0,
                    "total_income": 0.0,
                    "status": "",
                }

            player_data[player_title]["total_tax"] += bounty_record.tax_isk

            # Update main character if we have one and haven't set it yet
            if main_character and not player_data[player_title]["main_character"]:
                player_data[player_title]["main_character"] = main_character

        # Process mining records
        for mining_record in upload.mining_records:
            character = mining_record.character
            if character and character.player:
                player_title = character.player.title
                player_id = character.player.id
                main_character = (
                    character.player.mainchar.name
                    if character.player.mainchar
                    else None
                )
            else:
                player_title = "__查无此人__"
                # Find the default player ID
                from kmstat.models import Player

                default_player = Player.query.filter_by(title="__查无此人__").first()
                player_id = default_player.id if default_player else None
                main_character = None

            if player_title not in player_data:
                player_data[player_title] = {
                    "player_title": player_title,
                    "player_id": player_id,
                    "main_character": main_character,
                    "total_tax": 0.0,
                    "total_mining_volume": 0.0,
                    "total_pap": 0.0,
                    "strategic_pap": 0.0,
                    "total_income": 0.0,
                    "status": "",
                }

            player_data[player_title]["total_mining_volume"] += mining_record.volume_m3

            # Update main character if we have one and haven't set it yet
            if main_character and not player_data[player_title]["main_character"]:
                player_data[player_title]["main_character"] = main_character

        # Calculate total income and status for each player
        from datetime import date

        first_day_of_month = date(upload.year, upload.month, 1)

        for player_title in player_data:
            player_info = player_data[player_title]
            tax_income = (
                player_info["total_tax"] / upload.tax_rate if upload.tax_rate > 0 else 0
            )
            ore_income = player_info["total_mining_volume"] * upload.ore_convert_rate
            player_info["total_income"] = tax_income + ore_income

            # Calculate status based on PAP and income
            total_pap = player_info["total_pap"]
            total_income = player_info["total_income"]

            if total_pap >= 3:
                player_info["status"] = "合格"
            elif total_pap < 3:
                # Find the player's join date
                from kmstat.models import Player

                player = Player.query.filter_by(title=player_title).first()
                if player and player.joindate:
                    days_since_join = (first_day_of_month - player.joindate.date()).days
                    if days_since_join < 90:
                        # 新人保护 has highest priority for new players regardless of income
                        player_info["status"] = "新人保护"
                    elif total_income >= 1_000_000_000:  # 1 billion ISK
                        fine_amount = 3 - total_pap
                        player_info["status"] = f"罚款：{fine_amount}"
                    else:
                        player_info["status"] = "低收入豁免"
                else:
                    # No join date, assume they need fine if high income
                    if total_income >= 1_000_000_000:  # 1 billion ISK
                        fine_amount = 3 - total_pap
                        player_info["status"] = f"罚款：{fine_amount}"
                    else:
                        player_info["status"] = "低收入豁免"
            else:
                player_info["status"] = "未知"

        # Convert to list and sort by total PAP (descending)
        player_summary = list(player_data.values())
        player_summary.sort(key=lambda x: x["total_pap"], reverse=True)

        return {
            "year": upload.year,
            "month": upload.month,
            "upload_date": upload.upload_date,
            "tax_rate": upload.tax_rate,
            "ore_convert_rate": upload.ore_convert_rate,
            "uploaded_by": upload.uploaded_by.username,
            "pap_records": len(upload.pap_records),
            "bounty_records": len(upload.bounty_records),
            "mining_records": len(upload.mining_records),
            "player_summary": player_summary,
        }

    @staticmethod
    def delete_upload(year: int, month: int) -> bool:
        """Delete an existing upload and all its data."""
        upload = MonthlyUpload.query.filter_by(year=year, month=month).first()
        if not upload:
            return False

        try:
            db.session.delete(upload)
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False

    @staticmethod
    def upload_exists(year: int, month: int) -> bool:
        """Check if upload data exists for the given year and month."""
        return MonthlyUpload.query.filter_by(year=year, month=month).first() is not None

    @staticmethod
    def _process_pap_sheet_with_session(
        df: pd.DataFrame, upload: MonthlyUpload, session
    ) -> int:
        """Process PAP sheet data with a specific database session."""
        if df.empty:
            return 0

        # Validate columns
        expected_cols = ["名字", "Title", "PAP", "战略PAP"]
        missing_cols = [col for col in expected_cols if col not in df.columns]
        if missing_cols:
            raise UploadError(f"PAP sheet missing columns: {', '.join(missing_cols)}")

        count = 0
        for _, row in df.iterrows():
            # Skip rows with missing essential data
            if pd.isna(row["名字"]) or pd.isna(row["Title"]):
                continue

            character_name = str(row["名字"]).strip()
            player_title = str(row["Title"]).strip()
            pap_points = float(row["PAP"]) if not pd.isna(row["PAP"]) else 0.0
            strategic_pap = (
                float(row["战略PAP"]) if not pd.isna(row["战略PAP"]) else 0.0
            )

            # Find or create character with player association using the session
            # Try to find existing character first to avoid API calls in threads
            character = session.query(Character).filter_by(name=character_name).first()
            if not character:
                # Character doesn't exist - for thread safety, create minimal character
                # without API calls and associate with player
                from kmstat.models import Player

                # Find or create player
                player = session.query(Player).filter_by(title=player_title).first()
                if not player:
                    player = Player(title=player_title)
                    session.add(player)
                    session.flush()

                # Create character with minimal info (no API call or ESI validation)
                # Note: We don't set an explicit ID since SQLAlchemy will auto-generate it
                character = Character(
                    name=character_name, title=player_title, player=player
                )
                session.add(character)
                session.flush()

            pap_record = PAPRecord(
                upload=upload,
                character=character,
                pap_points=pap_points,
                strategic_pap_points=strategic_pap,
            )
            session.add(pap_record)
            count += 1

        return count

    @staticmethod
    def _process_bounty_sheet_with_session(
        df: pd.DataFrame, upload: MonthlyUpload, session
    ) -> int:
        """Process bounty sheet data with a specific database session."""
        if df.empty:
            return 0

        # Validate columns
        expected_cols = ["名字", "纳税(isk)"]
        missing_cols = [col for col in expected_cols if col not in df.columns]
        if missing_cols:
            raise UploadError(
                f"Bounty sheet missing columns: {', '.join(missing_cols)}"
            )

        count = 0
        for _, row in df.iterrows():
            # Skip rows with missing essential data
            if pd.isna(row["名字"]) or pd.isna(row["纳税(isk)"]):
                continue

            character_name = str(row["名字"]).strip()
            tax_isk = float(row["纳税(isk)"])

            # Find or create character (no player title provided in bounty sheet)
            character = session.query(Character).filter_by(name=character_name).first()
            if not character:
                # Character doesn't exist - create minimal character without API calls
                from kmstat.models import Player

                # Associate with default player
                default_player = (
                    session.query(Player).filter_by(title="__查无此人__").first()
                )
                if not default_player:
                    default_player = Player(title="__查无此人__")
                    session.add(default_player)
                    session.flush()

                # Create character with minimal info (no API call)
                character = Character(name=character_name, player=default_player)
                session.add(character)
                session.flush()

            bounty_record = BountyRecord(
                upload=upload, character=character, tax_isk=tax_isk
            )
            session.add(bounty_record)
            count += 1

        return count

    @staticmethod
    def _process_mining_sheet_with_session(
        df: pd.DataFrame, upload: MonthlyUpload, session
    ) -> int:
        """Process mining sheet data with a specific database session."""
        if df.empty:
            return 0

        # Validate columns
        expected_cols = ["名字", "主人物", "体积(m3)"]
        missing_cols = [col for col in expected_cols if col not in df.columns]
        if missing_cols:
            raise UploadError(
                f"Mining sheet missing columns: {', '.join(missing_cols)}"
            )

        count = 0
        for _, row in df.iterrows():
            # Skip rows with missing essential data
            if pd.isna(row["名字"]) or pd.isna(row["体积(m3)"]):
                continue

            character_name = str(row["名字"]).strip()
            main_character_name = (
                str(row["主人物"]).strip() if not pd.isna(row["主人物"]) else ""
            )
            volume_m3 = float(row["体积(m3)"])

            # Find or create character
            character = session.query(Character).filter_by(name=character_name).first()
            if not character:
                # Character doesn't exist - create minimal character without API calls
                from kmstat.models import Player

                player = None
                # Handle character association with player based on main character
                if main_character_name:
                    # Try to find the main character to get the player title
                    main_char = (
                        session.query(Character)
                        .filter_by(name=main_character_name)
                        .first()
                    )
                    if main_char and main_char.player:
                        # Associate with the same player as the main character
                        player = main_char.player

                if not player:
                    # No main character or player found, use default
                    player = (
                        session.query(Player).filter_by(title="__查无此人__").first()
                    )
                    if not player:
                        player = Player(title="__查无此人__")
                        session.add(player)
                        session.flush()

                # Create character with minimal info (no API call)
                character = Character(name=character_name, player=player)
                session.add(character)
                session.flush()

            mining_record = MiningRecord(
                upload=upload, character=character, volume_m3=volume_m3
            )
            session.add(mining_record)
            count += 1

        return count
