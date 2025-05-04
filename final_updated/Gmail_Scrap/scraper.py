from __future__ import print_function
import base64
from bs4 import BeautifulSoup
import io
import email
import boto3
from datetime import datetime
from datetime import timedelta
import pandas as pd
import logging
import re
import subprocess
import os
import time
import traceback
import csv
import json
import sys

import os.path
from email.mime.text import MIMEText
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from typing import List, Tuple
from halo import Halo

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Importing email and label ID from config
try:
    from config import EMAIL_ID, LABEL_ID
except ImportError:
    # If direct import fails, try with the full module path
    from Gmail_Scrap.config import EMAIL_ID, LABEL_ID

# Fetching date from 3 months ago to get more transactions
dt = (datetime.today() - timedelta(days=90)).replace(hour=0, minute=0, second=0, microsecond=0).date()
dt = str(dt)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def extract_phonepe_details(messageBody: str) -> tuple:
    """
    Extract transaction details from PhonePe email
    Returns: (amount, recipient, transaction_type, txn_id, txn_status, debited_from, bank_ref_no, message)
    """
    try:
        # Handle potential encoding issues by replacing problematic characters
        cleaned_message = messageBody.replace('\xa0', ' ')
        
        # Replace Rupee symbol with 'Rs.' to avoid encoding issues
        cleaned_message = cleaned_message.replace('₹', 'Rs.')
        
        # Log message safely (limited to 200 chars to avoid log bloat)
        try:
            preview = cleaned_message[:200] + "..." if len(cleaned_message) > 200 else cleaned_message
            logging.debug(f'Processing message: {preview}')
        except UnicodeEncodeError:
            logging.debug('Message contains characters that cannot be encoded in the console charset')
            
        # Check for verification emails which are not transaction emails
        if "verification" in cleaned_message.lower() or "verify this email" in cleaned_message.lower() or "digit code" in cleaned_message.lower():
            logging.info("Skipping email verification message, not a transaction")
            return 0, "None", "none", "", "", "", "", ""
            
        # Extract amount using regex patterns
        amount_pattern = r'(?:Rs\.?|INR)\s*(\d+(?:,\d+)*(?:\.\d+)?)'
        amount_match = re.search(amount_pattern, cleaned_message, re.IGNORECASE)
        
        if amount_match:
            amount_str = amount_match.group(1).replace(',', '')
            amount = float(amount_str)
        else:
            # Try alternative pattern that might appear in some emails
            alt_amount_pattern = r'(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:Rs\.?|INR)'
            alt_match = re.search(alt_amount_pattern, cleaned_message, re.IGNORECASE)
            if alt_match:
                amount_str = alt_match.group(1).replace(',', '')
                amount = float(amount_str)
            else:
                # Look for numbers that might be amounts
                number_pattern = r'Paid\s+to.*?[\r\n\s]+([A-Za-z0-9\s]+)[\r\n\s]+.*?(\d+(?:,\d+)*(?:\.\d+)?)'
                number_match = re.search(number_pattern, cleaned_message)
                if number_match:
                    amount_str = number_match.group(2).replace(',', '')
                    try:
                        amount = float(amount_str)
                    except ValueError:
                        amount = 0
                else:
                    amount = 0
        
        # Extract recipient name
        recipient_pattern = r'Paid\s+to[\r\n\s]+(.*?)(?=[\r\n\s]+.*?(?:Rs\.?|INR|\d{3}|Txn))'
        recipient_match = re.search(recipient_pattern, cleaned_message, re.IGNORECASE | re.DOTALL)
        
        if recipient_match:
            recipient = recipient_match.group(1).strip()
        else:
            # Try to find merchant name or payee with a broader pattern
            merchant_pattern = r'(?:Paid to|payment to|sent to)[\r\n\s]+(.*?)(?=[\r\n\s]+|$)'
            merchant_match = re.search(merchant_pattern, cleaned_message, re.IGNORECASE | re.DOTALL)
            if merchant_match:
                recipient = merchant_match.group(1).strip()
            else:
                recipient = "Unknown"
        
        # Clean up recipient name - remove extra spaces and special characters
        recipient = re.sub(r'\s+', ' ', recipient).strip()
        recipient = re.sub(r'=+$', '', recipient).strip()
        
        # Determine transaction type
        if 'refund' in cleaned_message.lower():
            transaction_type = 'refund'
        elif 'received' in cleaned_message.lower():
            transaction_type = 'credit'
        else:
            transaction_type = 'payment'
        
        # Extract transaction ID
        txn_id_pattern = r'Txn\.\s*ID\s*:?\s*([A-Za-z0-9]+)'
        txn_id_match = re.search(txn_id_pattern, cleaned_message, re.IGNORECASE)
        txn_id = txn_id_match.group(1) if txn_id_match else ""
        
        # Extract transaction status
        status_pattern = r'Txn\.\s*status\s*:?\s*(\w+)'
        status_match = re.search(status_pattern, cleaned_message, re.IGNORECASE)
        txn_status = status_match.group(1) if status_match else ""
        
        # Extract debited from account
        debited_pattern = r'Debited\s+from\s*:?\s*(.*?)(?=[\r\n]|Bank\s+Ref|$)'
        debited_match = re.search(debited_pattern, cleaned_message, re.IGNORECASE | re.DOTALL)
        debited_from = debited_match.group(1).strip() if debited_match else ""
        
        # Extract bank reference number if available
        ref_pattern = r'Bank\s+Ref\.\s*No\.\s*:?\s*(\d+)'
        ref_match = re.search(ref_pattern, cleaned_message, re.IGNORECASE)
        bank_ref_no = ref_match.group(1).strip() if ref_match else ""
        
        # Extract message if available (limited to avoid capturing too much)
        message_pattern = r'Message\s*:\s*(.*?)(?=Important Note|About us|$)'
        message_match = re.search(message_pattern, cleaned_message, re.IGNORECASE | re.DOTALL)
        message_text = message_match.group(1).strip() if message_match else ""
        
        # Limit message length to avoid issues
        if message_text and len(message_text) > 200:
            message_text = message_text[:197] + "..."
        
        # Log the extracted data
        try:
            logging.info(f"Extracted Amount: {amount}, Recipient: {recipient}, Type: {transaction_type}, Txn ID: {txn_id}, Txn Status: {txn_status}, Debited From: {debited_from}, Bank Ref No: {bank_ref_no}")
        except UnicodeEncodeError:
            logging.info(f"Extracted Amount: {amount}, Type: {transaction_type}, Txn ID: {txn_id}")
        
        return amount, recipient, transaction_type, txn_id, txn_status, debited_from, bank_ref_no, message_text
    except Exception as e:
        logging.error(f"Error extracting details: {str(e)}")
        return 0, "Unknown", "payment", "", "", "", "", ""

def main(force_refresh=False, progress_callback=None):
    """Main execution function for the Gmail scraper"""
    setup_logging()
    
    # Try to load cached data if force_refresh is False
    if not force_refresh:
        cached_data = load_cached_data()
        if cached_data:
            logging.info("Using cached data instead of fetching from Gmail")
            if progress_callback:
                progress_callback("Using cached data", 100)
            return cached_data
    
    # If we get here, either force_refresh=True or no cached data exists
    if progress_callback:
        progress_callback("Authorizing Gmail API", 5)

    try:
        # Fetch emails from Gmail
        service = authorize_gmail()
        
        # We'll use the existing search_phonepe_emails function
        if progress_callback:
            progress_callback("Searching for transaction emails", 10)
            
        # Use search_phonepe_emails instead of search_messages
        messages = search_phonepe_emails(service)
        
        if not messages:
            logging.warning("No PhonePe transaction emails found")
            if progress_callback:
                progress_callback("No transaction emails found", 100)
            return []
        
        logging.info(f"Found {len(messages)} emails matching the search criteria")
        if progress_callback:
            progress_callback(f"Found {len(messages)} emails", 15)
        
        # Process emails
        all_transactions = []
        total_emails = len(messages)
        
        for index, msg_id in enumerate(messages):
            if progress_callback:
                # Calculate progress between 15-95%
                progress_percent = 15 + int((index / total_emails) * 80)
                progress_callback(f"Processing emails ({index+1}/{total_emails})", progress_percent)
                
            logging.debug(f"Processing email {index+1}/{total_emails}")
            
            try:
                email = get_email(service, msg_id)
                
                # Try to parse this email
                transactions = parse_email(email)
                if transactions:
                    all_transactions.extend(transactions)
            except Exception as e:
                logging.error(f"Error processing email {msg_id}: {str(e)}")
        
        if progress_callback:
            progress_callback("Saving transaction data", 95)
            
        # Save as cached data
        if all_transactions:
            save_as_csv(all_transactions)
            logging.info(f"Saved {len(all_transactions)} transactions as cached data")
        else:
            logging.warning("No transactions to save")
        
        if progress_callback:
            if all_transactions:
                progress_callback(f"Processed {len(all_transactions)} transactions", 100)
            else:
                progress_callback("No transactions found. Please try again or check your Gmail account.", 100)
                
        return all_transactions
    except Exception as e:
        logging.error(f"Error in main function: {str(e)}")
        if progress_callback:
            progress_callback(f"Error: {str(e)}", 100)
        return []

def setup_logging():
    """Set up logging configuration with proper encoding handling"""
    # Configure root logger
    import io
    import sys
    import locale
    
    # Get system locale and encoding info for debugging
    system_locale = locale.getlocale()
    
    # Force UTF-8 encoding for stdout/stderr
    try:
        # For Windows, we need to handle console encoding differently
        if sys.platform == 'win32':
            # Try to use UTF-8 for console output
            sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
            sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
        else:
            # For Unix-like systems
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='backslashreplace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='backslashreplace')
    except Exception as e:
        # If reconfiguration fails, log it but continue
        print(f"Warning: Could not reconfigure stdout/stderr: {e}")
    
    # Configure logging to handle Unicode properly
    log_file = os.path.join(os.path.dirname(__file__), 'scraper.log')
    
    # Create a custom formatter that handles encoding issues
    class SafeFormatter(logging.Formatter):
        def format(self, record):
            try:
                return super().format(record)
            except UnicodeEncodeError:
                # If there's an encoding error, replace problematic characters
                record.msg = str(record.msg).encode('utf-8', 'replace').decode('utf-8')
                if hasattr(record, 'args') and record.args:
                    record.args = tuple(
                        str(arg).encode('utf-8', 'replace').decode('utf-8') 
                        if isinstance(arg, str) else arg 
                        for arg in record.args
                    )
                return super().format(record)
    
    # Create formatter with safe encoding
    formatter = SafeFormatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Set up handlers
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    
    stream_handler = logging.StreamHandler(stream=sys.stdout)
    stream_handler.setFormatter(formatter)
    
    # Remove any existing handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Configure root logger
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
    
    # Log system information for debugging
    logging.info(f"System locale: {system_locale}")
    logging.info(f"Console encoding: {sys.stdout.encoding}")
    logging.info(f"Python version: {sys.version}")
    logging.info(f"Platform: {sys.platform}")
    
    # Test Unicode handling
    test_string = "Testing Unicode: ₹ € £ ¥ 漢字 Русский 🙂"
    try:
        logging.info(test_string)
    except Exception as e:
        logging.error(f"Unicode test failed: {e}")
    
    logging.info("Logging configured successfully")

def authorize_gmail(api_key=None):
    """Authorize and get Gmail service client"""
    creds = None
    token_path = os.path.join(os.path.dirname(__file__), 'token.json')
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            credentials_path = os.path.join(os.path.dirname(__file__), 'credentials.json')
            if not os.path.exists(credentials_path):
                logging.error(f"Credentials file not found at {credentials_path}")
                raise FileNotFoundError(f"Credentials file not found at {credentials_path}")
                
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    
    try:
        service = build('gmail', 'v1', credentials=creds)
        return service
    except Exception as e:
        logging.error(f"Error building Gmail service: {str(e)}")
        raise

def search_phonepe_emails(service):
    """Search for PhonePe transaction emails"""
    try:
        # Get emails from the last 3 months
        date_limit = (datetime.now() - timedelta(days=90)).strftime('%Y/%m/%d')
        search_query = f"(from:support@phonepe.com OR from:no-reply@phonepe.com OR from:noreply@phonepe.com OR subject:PhonePe) after:{date_limit}"
        
        logging.info(f"Searching for emails with query: {search_query}")
        
        results = service.users().messages().list(
            userId='me',
            q=search_query,
            maxResults=100
        ).execute()
        
        messages = results.get('messages', [])
        
        if not messages:
            logging.warning("No PhonePe emails found")
            return []
            
        logging.info(f"Found {len(messages)} PhonePe emails")
        return [msg['id'] for msg in messages]
    
    except Exception as e:
        logging.error(f"Error searching for PhonePe emails: {str(e)}")
        return []

def get_email(service, email_id):
    """Get email content by ID"""
    try:
        message = service.users().messages().get(userId='me', id=email_id, format='raw').execute()
        logging.info(f"Retrieved email ID: {email_id}")
        
        # Decode the raw message
        msg_bytes = base64.urlsafe_b64decode(message['raw'].encode('ASCII'))
        mime_msg = email.message_from_bytes(msg_bytes)
        
        # Extract date from message
        email_date = datetime.fromtimestamp(int(message['internalDate'])/1000).strftime('%Y-%m-%d')
        
        # Extract email body
        if mime_msg.is_multipart():
            for part in mime_msg.get_payload():
                if part.get_content_type() == 'text/plain':
                    body = part.get_payload()
                    break
            else:
                body = ""
        else:
            body = mime_msg.get_payload()
        
        return {
            'id': email_id,
            'date': email_date,
            'body': body
        }
    
    except Exception as e:
        logging.error(f"Error retrieving email {email_id}: {str(e)}")
        return None

def parse_email(email_data):
    """Parse PhonePe email for transaction details"""
    if not email_data or 'body' not in email_data:
        return []
        
    try:
        body = email_data['body']
        email_date = email_data['date']
        
        # Properly decode MIME Quoted-Printable format
        try:
            # First try to decode any MIME Quoted-Printable encoding
            import quopri
            import email.parser
            
            # Check if the body has MIME encoding characteristics
            if "=20" in body or "=\r\n" in body or "=3D" in body:
                decoded_body = quopri.decodestring(body.encode('utf-8', errors='replace'))
                body = decoded_body.decode('utf-8', errors='replace')
                
                # Clean up common MIME artifacts
                body = body.replace('=20', ' ')
                body = body.replace('=\r\n', '')
                body = body.replace('=3D', '=')
                body = body.replace('=E2=82=B9', '₹')  # Rupee symbol
                body = body.replace('=C2=A0', ' ')     # Non-breaking space
                
                logging.debug("Email decoded from MIME Quoted-Printable format")
        except Exception as e:
            logging.warning(f"Error decoding MIME format: {str(e)}")
        
        # Use the extract_phonepe_details function on the decoded body
        amount, recipient, transaction_type, txn_id, txn_status, debited_from, bank_ref_no, message = extract_phonepe_details(body)
        
        # Validate the extracted data
        if amount and float(amount) > 0 and recipient and recipient != "=" and txn_id:
            transaction = {
                'Date': email_date,
                'Recipient': recipient,
                'Amount': amount,
                'Payment Mode': 'phonepe',
                'Type': transaction_type,
                'Txn ID': txn_id,
                'Txn Status': txn_status,
                'Debited From': debited_from,
                'Bank Ref No': bank_ref_no,
                'Message': message
            }
            logging.info(f"Successfully extracted transaction data: {recipient}, Amount: {amount}")
            return [transaction]
        else:
            logging.warning(f"Extracted data failed validation: amount={amount}, recipient={recipient}, txn_id={txn_id}")
    except Exception as e:
        logging.error(f"Error parsing email: {str(e)}")
    
    return []

def clean_transactions(transactions):
    """Clean and deduplicate transactions"""
    if not transactions:
        return []
        
    # Convert to DataFrame for easier manipulation
    df = pd.DataFrame(transactions)
    
    # Remove duplicates based on transaction ID if available
    if 'Txn ID' in df.columns:
        df = df.drop_duplicates(subset=['Txn ID'])
    
    # Remove duplicate date-recipient-amount combinations
    df = df.drop_duplicates(subset=['Date', 'Recipient', 'Amount'])
    
    # Sort by date
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values('Date', ascending=False)
        df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
    
    logging.info(f"Cleaned transactions: {len(df)} (from {len(transactions)} raw transactions)")
    return df.to_dict('records')

def save_transactions_to_csv(transactions, file_path):
    """Save transactions to CSV file"""
    if not transactions:
        logging.warning("No transactions to save")
        return False
        
    try:
        df = pd.DataFrame(transactions)
        df.to_csv(file_path, index=False)
        logging.info(f"Saved {len(transactions)} transactions to {file_path}")
        return True
    except Exception as e:
        logging.error(f"Error saving transactions to CSV: {str(e)}")
        return False

def load_transactions_from_csv(file_path):
    """Load transactions from CSV file"""
    try:
        if not os.path.exists(file_path):
            logging.warning(f"CSV file does not exist: {file_path}")
            return []
            
        df = pd.read_csv(file_path)
        transactions = df.to_dict('records')
        logging.info(f"Loaded {len(transactions)} transactions from {file_path}")
        return transactions
    except Exception as e:
        logging.error(f"Error loading transactions from CSV: {str(e)}")
        return []

def load_cached_data():
    """Load transactions data from cache file if available and recent"""
    cache_file = os.path.join(os.path.dirname(__file__), 'cached_transactions.csv')
    
    if not os.path.exists(cache_file):
        logging.info("No cache file found")
        return None
        
    # Check if cache is recent (less than 1 hour old)
    cache_time = os.path.getmtime(cache_file)
    current_time = time.time()
    cache_age_minutes = (current_time - cache_time) / 60
    
    if cache_age_minutes > 60:  # Cache older than 1 hour
        logging.info(f"Cache exists but is too old ({cache_age_minutes:.1f} minutes)")
        return None
    
    try:
        # Read the CSV file
        import pandas as pd
        df = pd.read_csv(cache_file, encoding='utf-8')
        
        # Convert DataFrame to list of dictionaries
        transactions = df.to_dict('records')
        
        logging.info(f"Loaded {len(transactions)} transactions from cache (age: {cache_age_minutes:.1f} minutes)")
        return transactions
    except Exception as e:
        logging.error(f"Error loading cached data: {str(e)}")
        return None

def save_as_csv(transactions):
    """Save transactions to a CSV file for caching"""
    if not transactions:
        logging.warning("No transactions to save")
        return
    
    try:
        # Create a DataFrame from the transactions
        import pandas as pd
        df = pd.DataFrame(transactions)
        
        # Save to CSV
        cache_file = os.path.join(os.path.dirname(__file__), 'cached_transactions.csv')
        df.to_csv(cache_file, index=False, encoding='utf-8')
        
        logging.info(f"Saved {len(transactions)} transactions to {cache_file}")
    except Exception as e:
        logging.error(f"Error saving to CSV: {str(e)}")

if __name__ == '__main__':
    main()

