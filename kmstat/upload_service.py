"""
Service for handling monthly Excel file uploads.
"""

import pandas as pd
from datetime import datetime
from flask import current_app
from kmstat import db
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
            # If overwriting, delete existing data first
            if existing and overwrite:
                MonthlyUploadService.delete_upload(year, month)

            # Read Excel file
            excel_data = pd.read_excel(file_path, sheet_name=None)

            # Validate required sheets
            required_sheets = ["PAP", "赏金", "挖矿"]
            missing_sheets = [
                sheet for sheet in required_sheets if sheet not in excel_data
            ]
            if missing_sheets:
                raise UploadError(
                    f"Missing required sheets: {', '.join(missing_sheets)}"
                )

            # Create upload record
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

            # Process each sheet
            pap_count = MonthlyUploadService._process_pap_sheet(
                excel_data["PAP"], upload
            )
            bounty_count = MonthlyUploadService._process_bounty_sheet(
                excel_data["赏金"], upload
            )
            mining_count = MonthlyUploadService._process_mining_sheet(
                excel_data["挖矿"], upload
            )

            db.session.commit()

            current_app.logger.info(
                f"Successfully uploaded {year}-{month:02d}: "
                f"{pap_count} PAP records, {bounty_count} bounty records, "
                f"{mining_count} mining records"
            )

            return upload

        except Exception as e:
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

            # Find or create character with player association
            character = Character.find_or_create_by_name(character_name, player_title)

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

            # Find or create character (no player title provided in bounty sheet)
            character = Character.find_or_create_by_name(character_name)

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

            # Handle character association with player based on main character
            if main_character_name:
                # Try to find the main character to get the player title
                main_char = Character.query.filter_by(name=main_character_name).first()
                if main_char and main_char.player:
                    # Associate with the same player as the main character
                    character = Character.find_or_create_by_name(
                        character_name, main_char.player.title
                    )
                else:
                    # Main character not found or has no player, create without player
                    character = Character.find_or_create_by_name(character_name)
            else:
                # No main character specified, create without player
                character = Character.find_or_create_by_name(character_name)

            mining_record = MiningRecord(
                upload=upload, character=character, volume_m3=volume_m3
            )
            db.session.add(mining_record)
            count += 1

        return count

    @staticmethod
    def get_upload_summary(upload: MonthlyUpload) -> dict:
        """Get a summary of an upload."""
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
