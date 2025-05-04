import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
import os
from .error_handler import ExpenseTrackerError, SheetNotFoundError, display_error_and_exit
import logging

def prepare_data_for_sheets(data):
    if not data or not isinstance(data, list):
        raise ValueError("Data must be a non-empty list")

    if not all(isinstance(row, list) and len(row) == 3 for row in data):
        raise ValueError("Each row must be a list with exactly 3 elements")

    prepared_data = []
    for row in data:
        item, category, amount = row
        prepared_data.append([str(item), str(category), float(amount)])

    return prepared_data

def write_to_sheet(data, sheet_name=None):
    """
    Stub implementation of write_to_sheet function.
    This is a placeholder for the actual implementation.
    
    Args:
        data: The data to write to the sheet
        sheet_name: Optional name of the sheet to write to
        
    Returns:
        A boolean indicating success (always True for this stub)
    """
    logging.info("Stub write_to_sheet called - no actual sheet writing functionality implemented")
    if data:
        logging.info(f"Would have written {len(data)} records to sheet {sheet_name}")
    return True

if __name__ == "__main__":
    # Test data
    try:
        test_values = [
            ["spesa", "Grocery + Essentials", 20],
            ["spesa", "Grocery + Essentials", 40],
            ["spesa", "Grocery + Essentials", 50]
        ]
        write_to_sheet(test_values, sheet_name='Test')
    except ExpenseTrackerError as e:
        display_error_and_exit(str(e))