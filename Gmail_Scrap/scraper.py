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

import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from typing import List, Tuple

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Importing email and label ID from config
from config import EMAIL_ID, LABEL_ID

# Fetching date from 3 months ago to get more transactions
dt = (datetime.today() - timedelta(days=90)).replace(hour=0, minute=0, second=0, microsecond=0).date()
dt = str(dt)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def extract_phonepe_details(messageBody: str) -> tuple:
    """Extract payment details from PhonePe email body."""
    try:
        # Handle both string and bytes input
        if isinstance(messageBody, bytes):
            messageBody = messageBody.decode('utf-8', errors='ignore')
        
        # Decode any encoded characters and clean up the message
        try:
            messageBody = messageBody.encode('utf-8').decode('unicode_escape')
        except (UnicodeError, AttributeError):
            # If decoding fails, use the original message
            pass
        
        # Initial cleaning of the message body
        cleaned_message = re.sub(r'=\r\n', '', messageBody)  # Remove line continuation markers
        cleaned_message = re.sub(r'=E2=82=B9', '₹', cleaned_message)  # Replace encoded rupee symbol
        cleaned_message = re.sub(r'=C2=A0', ' ', cleaned_message)  # Replace encoded spaces
        cleaned_message = re.sub(r'=20', ' ', cleaned_message)  # Replace more encoded spaces
        cleaned_message = re.sub(r'=\s*$', '', cleaned_message, flags=re.MULTILINE)  # Remove trailing = characters
        cleaned_message = re.sub(r'[\s]+', ' ', cleaned_message).strip()  # Normalize whitespace
        
        logging.debug(f'Cleaned Message: {cleaned_message}')
        
        # Skip processing if it's a promotional email or verification code
        if any(promo in cleaned_message.lower() for promo in ['recharge codes', 'verify this email', 'digit code']):
            logging.info("Skipping promotional email")
            return None, None, None, None, None, None, None, None
        
        amount, recipient, transaction_type = None, None, "payment"
        txn_id, txn_status, debited_from, bank_ref_no, message = None, None, None, None, None
        
        # Enhanced regex patterns
        paid_to_pattern = r'(?:Paid to|Paid)\s+(.*?)(?=\s*(?:₹|Rs\.?|\s+Txn\.|\s+on|\s+at|$))'
        amount_pattern = r'(?:₹|Rs\.?)\s*(\d+(?:,\d{3})*(?:\.\d{2})?)'
        bill_payment_pattern = r'Payment For (\d+[A-Z0-9]+)\s*(?:₹|Rs\.?)\s*(\d+(?:,\d{3})*(?:\.\d{2})?)'
        sent_pattern = r'Sent\s*(?:₹|Rs\.?)\s*(\d+(?:,\d{3})*(?:\.\d{2})?)\s*to\s*(.*?)(?=\s*(?:-|\s*on|\s*at|$))'
        txn_id_pattern = r'Txn\. ID\s*:\s*(\S+)'
        txn_status_pattern = r'Txn\. status\s*:\s*(\S+)'
        debited_from_pattern = r'Debited from\s*:\s*(.*?)(?=\s*Bank Ref\. No\.|$)'
        bank_ref_no_pattern = r'Bank Ref\. No\s*:\s*(\S+)'
        message_pattern = r'Message\s*:\s*(.*?)(?=\s*Important Note|$)'
        
        # Try to extract from bill payment format first
        bill_match = re.search(bill_payment_pattern, cleaned_message)
        if bill_match:
            recipient = f"Bill Payment - {bill_match.group(1)}"
            amount = bill_match.group(2)
            transaction_type = "bill_payment"
        else:
            # Try to extract recipient using the paid_to pattern
            paid_to_match = re.search(paid_to_pattern, cleaned_message)
            if paid_to_match:
                recipient = paid_to_match.group(1).strip()
            
            # Try to extract amount
            amount_match = re.search(amount_pattern, cleaned_message)
            if amount_match:
                amount = amount_match.group(1).strip()
                
            # Check for "Sent" format
            sent_match = re.search(sent_pattern, cleaned_message)
            if sent_match:
                amount = sent_match.group(1).strip()
                recipient = sent_match.group(2).strip()
                transaction_type = "sent"
        
        # Extract additional fields
        txn_id_match = re.search(txn_id_pattern, cleaned_message)
        if txn_id_match:
            txn_id = txn_id_match.group(1).strip()
        
        txn_status_match = re.search(txn_status_pattern, cleaned_message)
        if txn_status_match:
            txn_status = txn_status_match.group(1).strip()
        
        debited_from_match = re.search(debited_from_pattern, cleaned_message)
        if debited_from_match:
            debited_from = debited_from_match.group(1).strip()
        
        bank_ref_no_match = re.search(bank_ref_no_pattern, cleaned_message)
        if bank_ref_no_match:
            bank_ref_no = bank_ref_no_match.group(1).strip()
        
        message_match = re.search(message_pattern, cleaned_message)
        if message_match:
            message = message_match.group(1).strip()
        else:
            message = 'empty'  # Set to 'empty' if no note is present
        
        # If no amount found yet, try looking for it in a broader context
        if not amount:
            # Look for any number following a ₹ symbol
            broader_amount = re.search(r'₹\s*(\d+)', cleaned_message)
            if broader_amount:
                amount = broader_amount.group(1).strip()
        
        # Additional cleaning of recipient if found
        if recipient:
            recipient = re.sub(r'\s+', ' ', recipient).strip()
            recipient = recipient.replace('=', '').strip()
            
        # Log the extracted values
        logging.info(f'Extracted Amount: {amount}, Recipient: {recipient}, Type: {transaction_type}, Txn ID: {txn_id}, Txn Status: {txn_status}, Debited From: {debited_from}, Bank Ref No: {bank_ref_no}, Message: {message}')
        
        if amount is None or recipient is None:
            logging.warning(f"Extraction failed for message: {cleaned_message}")
            
        return amount, recipient, transaction_type, txn_id, txn_status, debited_from, bank_ref_no, message
        
    except Exception as e:
        logging.error(f"Error extracting details: {e}")
        return None, None, None, None, None, None, None, None

def main():
    try:
        logging.info('Starting the script...')
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if not creds or not creds.valid:
            logging.warning('No valid credentials found. Attempting to refresh or reauthorize.')
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        logging.info('Credentials loaded successfully.')
        msgIdList = []
        bodyList = []
        try:
            service = build('gmail', 'v1', credentials=creds)
            search_query = "(from:support@phonepe.com OR from:no-reply@phonepe.com OR from:noreply@phonepe.com OR subject:PhonePe) after:" + dt
            logging.info(f'Searching for emails with query: {search_query}')
            results = service.users().messages().list(
                userId='me',
                q=search_query
            ).execute()
            msgIdDict = results.get('messages', [])
            logging.info(f'Found {len(msgIdDict)} messages.')
            for item in msgIdDict:
                msg_id = item['id']
                msgIdList.append(msg_id)
            logging.info('Processing messages...')
            for msg in msgIdList:
                message = service.users().messages().get(
                    userId='me', id=msg, format='raw').execute()
                logging.info(f'Fetched message ID: {msg}')  
                messageBody = base64.urlsafe_b64decode(
                    message['raw'].encode('ASCII'))
                msg_str = email.message_from_bytes(messageBody)
                email_date = datetime.fromtimestamp(
                    int(message['internalDate'])/1000
                ).strftime('%Y-%m-%d')
                if msg_str.is_multipart():
                    for part in msg_str.get_payload():
                        if part.get_content_type() == 'text/plain':
                            messageBody = part.get_payload()
                            break
                else:
                    messageBody = msg_str.get_payload()
                amount, recipient, transaction_type, txn_id, txn_status, debited_from, bank_ref_no, message = extract_phonepe_details(messageBody)
                if amount and recipient:
                    row = [email_date, recipient, amount, 'phonepe', transaction_type, txn_id, txn_status, debited_from, bank_ref_no, message]
                    bodyList.append(row)
            df = pd.DataFrame(
                bodyList, 
                columns=['Date', 'Recipient', 'Amount', 'Payment Mode', 'Type', 'Txn ID', 'Txn Status', 'Debited From', 'Bank Ref No', 'Message']
            )
            logging.info('Exporting data to CSV...')
            df.to_csv('test_cleaned_phonepe_transactions.csv', index=False)
            logging.info('CSV export completed successfully.')
        except HttpError as error:
            logging.error(f'An error occurred: {error}')
    except Exception as e:
        logging.error(f'An unexpected error occurred: {e}')


if __name__ == '__main__':
    main()

