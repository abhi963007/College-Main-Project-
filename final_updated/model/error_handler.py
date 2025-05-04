import sys
import logging

class ExpenseTrackerError(Exception):
    """Custom exception class for the expense tracker application."""
    
    def __init__(self, message, error_code=None):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)

class AuthenticationError(ExpenseTrackerError):
    """Raised when authentication fails"""
    pass

class NoteNotFoundError(ExpenseTrackerError):
    """Raised when the specified note is not found"""
    pass

class SheetNotFoundError(ExpenseTrackerError):
    """Raised when the specified Google Sheet is not found"""
    pass

def display_error_and_exit(message, error_code=1):
    """Display an error message and exit the program."""
    logging.error(f"ERROR: {message}")
    print(f"\nERROR: {message}")
    print("The application will now exit.")
    sys.exit(error_code)

def display_warning(warning_message):
    print(f"\nWarning: {warning_message}")