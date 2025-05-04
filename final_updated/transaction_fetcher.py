import requests
import json
from datetime import datetime, timedelta

# Configuration
# IMPORTANT: Use the webhook URL configured in your n8n instance
# Use the production webhook URL instead of the test one
N8N_WEBHOOK_URL = "http://localhost:5678/webhook/transactions"  # Production URL

def fetch_transactions(start_date=None, end_date=None, test_mode=True):
    """
    Fetch transactions from the n8n API endpoint.
    
    Parameters:
    - start_date: Optional start date in YYYY-MM-DD format
    - end_date: Optional end date in YYYY-MM-DD format
    - test_mode: Whether to use test mode URL (not used anymore)
    
    Returns:
    - List of transaction objects, or an empty list if none are found
    """
    # We're using the production URL by default now
    url = N8N_WEBHOOK_URL if not test_mode else "http://localhost:5678/webhook-test/transactions"
    
    # Default to last 30 days if no dates provided
    if not start_date or not end_date:
        end = datetime.now()
        start = end - timedelta(days=30)
        start_date = start_date or start.strftime("%Y-%m-%d")
        end_date = end_date or end.strftime("%Y-%m-%d")
        print(f"Using default date range: {start_date} to {end_date}")
    
    # Prepare parameters
    params = {
        "fetch_type": "transactions",
        "start_date": start_date,
        "end_date": end_date
    }
    
    try:
        print(f"Fetching transactions from n8n API at {url}")
        print(f"Date range: {start_date} to {end_date}")
        
        # Make the API request with an increased timeout
        response = requests.get(url, params=params, timeout=60)  # Increased timeout to 60 seconds
        
        # Log the response status
        print(f"API response status: {response.status_code}")
        print(f"Response body: {response.text[:500]}")  # Print part of the response for debugging
        
        # Check if the request was successful
        if response.status_code == 200:
            try:
                data = response.json()
                
                # Handle different response formats
                transactions = []
                
                if isinstance(data, list):
                    # Filter out workflow start messages and only keep actual transaction data
                    transactions = [tx for tx in data if 'Transaction ID' in tx or 'transaction_id' in tx or 'txn_id' in tx]
                elif isinstance(data, dict):
                    # Check if this is just a workflow start message
                    if data.get('message') == 'Workflow was started':
                        print("Received workflow start message, but no transaction data")
                        return []
                    
                    # Check for transactions key  
                    if 'transactions' in data:
                        transactions = data['transactions']
                    # Check if this is a single transaction object with proper fields
                    elif any(key in data for key in ['Transaction ID', 'transaction_id', 'txn_id', 'Amount', 'amount']):
                        transactions = [data]
                
                transaction_count = len(transactions)
                print(f"Successfully fetched {transaction_count} transactions")
                return transactions
            except json.JSONDecodeError:
                print(f"Error parsing JSON response from {url}: {response.text[:200]}...")
                print("The response is not valid JSON. Make sure the 'Respond to Webhook' node in n8n is set to return JSON data.")
                return []
        elif response.status_code == 404:
            # Special handling for n8n webhook test mode
            try:
                error_data = response.json()
                error_msg = error_data.get("message", "")
                if "webhook" in error_msg:
                    print(f"\n⚠️ WEBHOOK ERROR: {error_msg}")
            except:
                pass
            
            print(f"Error response from {url}: {response.status_code}")
            print(f"Response content: {response.text[:200]}...")
            return []
        else:
            print(f"Error response from {url}: {response.status_code}")
            print(f"Response content: {response.text[:200]}...")
            return []
                
    except requests.exceptions.Timeout:
        print(f"\n⚠️ TIMEOUT ERROR: The request to {url} timed out. This means n8n took too long to respond.")
        print("This could be because the workflow is processing a lot of data or has complex operations.")
        print("\nTry using the production webhook instead of the test webhook:")
        print("1. Make sure your workflow is activated in n8n")
        print("2. Try again using test_mode=False")
        
    except requests.RequestException as e:
        print(f"Error connecting to n8n API at {url}: {str(e)}")
    
    # If we get here, the connection failed
    print("\n❌ Connection attempt failed.")
    
    print("\nTROUBLESHOOTING STEPS:")
    print("1. Make sure your n8n instance is running (http://localhost:5678)")
    print("2. Open your workflow with the webhook node")
    print("3. Make sure the workflow is ACTIVATED (toggle in top-right)")
    print("4. The webhook might be taking too long - try simplifying your workflow")
    print("5. Use the production webhook URL instead of the test webhook")
    
    return []

if __name__ == "__main__":
    # Example usage
    print("Fetching transactions for the last 30 days...")
    transactions = fetch_transactions()
    
    # Display results
    print(f"Found {len(transactions)} transactions")
    
    if transactions:
        print("\nSample transactions:")
        for idx, tx in enumerate(transactions[:5], 1):  # Show first 5 transactions
            print(f"{idx}. {tx.get('date')} - Rs.{tx.get('amount')} to {tx.get('recipient')} - {tx.get('status')}")
        
        if len(transactions) > 5:
            print(f"... and {len(transactions) - 5} more")
    else:
        print("No transactions found. Please check your n8n workflow and webhook URL.")
    
    print("\nTo use in your application, import the fetch_transactions function.")
    print("Example: from transaction_fetcher import fetch_transactions") 