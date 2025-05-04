# n8n Email Transaction Scraper

This setup replaces the Python-based Gmail_Scrap module with n8n, a workflow automation platform.

## Setup Instructions

### Prerequisites
- Docker and Docker Compose installed
- Gmail account with API access

### Installation

1. Start n8n using Docker Compose:
   ```bash
   docker-compose up -d
   ```

2. Access n8n via your browser:
   ```
   http://localhost:5678
   ```

3. Create an account and log in.

### Creating the Email Scraping Workflow

#### Option 1: Scheduled Automatic Fetching
1. Create a new workflow in n8n.

2. Add a "Schedule Trigger" node to run the workflow at regular intervals (e.g., every hour).

3. Add a "Gmail" node to connect to your Gmail account:
   - Configure OAuth authentication
   - Set the operation to "Get Emails"
   - Set search criteria to find PhonePe transaction emails, e.g., `from:no-reply@phonepe.com subject:"Transaction Details"`
   - Set the download attachments option to false

4. Add a "Function" node to extract transaction details:
   ```javascript
   // Example code to parse PhonePe emails
   const transactions = [];
   
   for (const item of $input.all()) {
     const email = item.json;
     
     // Extract data using regex patterns
     const amountMatch = email.content.match(/Rs\.\s*(\d+(\.\d+)?)/);
     const recipientMatch = email.content.match(/paid to\s*([^<]+)/);
     const transactionIdMatch = email.content.match(/Transaction ID\s*:\s*([A-Z0-9]+)/);
     const statusMatch = email.content.match(/Status\s*:\s*([A-Za-z]+)/);
     const dateMatch = email.content.match(/Date\s*:\s*([^<]+)/);
     
     if (amountMatch && recipientMatch && transactionIdMatch) {
       transactions.push({
         transaction_id: transactionIdMatch[1],
         amount: parseFloat(amountMatch[1]),
         recipient: recipientMatch[1].trim(),
         status: statusMatch ? statusMatch[1] : 'Unknown',
         date: dateMatch ? new Date(dateMatch[1].trim()) : new Date(),
         email_id: email.id
       });
     }
   }
   
   return [{ json: { transactions } }];
   ```

5. Add a "Google Sheets" node to store the transactions:
   - Configure authentication
   - Set the operation to "Append"
   - Choose your transaction tracking spreadsheet
   - Map the transaction fields to columns

6. Save and activate the workflow.

#### Option 2: On-Demand Fetching via Webhook

1. Create a new workflow in n8n.

2. Add a "Webhook" node as trigger:
   - Set to GET or POST method
   - Copy the generated webhook URL
   - You can add query parameters for date filtering (start_date, end_date)

3. Add a "Gmail" node to connect to your Gmail account (same as Option 1).

4. Add a "Function" node to extract transaction details (same as Option 1).

5. Add a "Respond to Webhook" node at the end:
   - Set response code to 200
   - Return data in JSON format: `{ "transactions": {{$json.transactions}} }`

6. Save and activate the workflow.

#### Option 3: Direct API Integration (Recommended)

1. Create a new workflow in n8n.

2. Add a "Webhook" node as trigger with method GET.

3. Add a "Gmail" node to connect to your Gmail account (same as before).

4. Add a "Function" node to extract transactions (same as before).

5. Add another "Function" node to filter by date (if provided in the request):
   ```javascript
   const input = $input.first().json;
   const transactions = input.transactions || [];
   
   // Get query parameters
   const startDate = $parameter.start_date ? new Date($parameter.start_date) : null;
   const endDate = $parameter.end_date ? new Date($parameter.end_date) : null;
   
   let filteredTransactions = transactions;
   
   // Filter by date if parameters provided
   if (startDate && endDate) {
     filteredTransactions = transactions.filter(transaction => {
       const txDate = new Date(transaction.date);
       return txDate >= startDate && txDate <= endDate;
     });
   }
   
   return [{ json: { transactions: filteredTransactions } }];
   ```

6. Add a "Respond to Webhook" node to return the filtered data.

7. Save and activate the workflow.

### Integration with Existing Flask Application

#### For Option 1 (Using Google Sheets)

```python
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from flask import jsonify

# Setup Google Sheets API
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SPREADSHEET_ID = 'your-spreadsheet-id'
RANGE_NAME = 'Sheet1!A:F'

def get_sheet_data():
    credentials = service_account.Credentials.from_service_account_file(
        'credentials.json', scopes=SCOPES)
    service = build('sheets', 'v4', credentials=credentials)
    
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
    values = result.get('values', [])
    
    if not values:
        return []
    
    # First row contains headers
    headers = values[0]
    transactions = []
    
    for row in values[1:]:
        transaction = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
        transactions.append(transaction)
    
    return transactions

@app.route('/transactions', methods=['GET'])
def get_transactions():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    transactions = get_sheet_data()
    
    # Filter by date if provided
    if start_date and end_date:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        filtered_transactions = [
            t for t in transactions 
            if start <= datetime.strptime(t['date'], '%Y-%m-%d') <= end
        ]
        
        return jsonify(filtered_transactions)
    
    return jsonify(transactions)
```

#### For Option 2 or 3 (Direct API Call)

```python
import requests
from flask import request, jsonify
from datetime import datetime

# The webhook URL from n8n
N8N_WEBHOOK_URL = "your-webhook-url-from-n8n"

@app.route('/transactions', methods=['GET'])
def get_transactions():
    # Get date filters from request if any
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # Prepare parameters for n8n webhook
    params = {}
    if start_date:
        params['start_date'] = start_date
    if end_date:
        params['end_date'] = end_date
    
    # Call n8n webhook to fetch and process emails
    response = requests.get(N8N_WEBHOOK_URL, params=params)
    
    if response.status_code == 200:
        return jsonify(response.json())
    else:
        return jsonify({"error": "Failed to fetch transactions", "status": response.status_code}), 500
```

### Automatic Data Synchronization

To ensure your application always has access to the latest transaction data, use **both** approaches:

1. Set up the scheduled workflow (Option 1) to run hourly/daily to keep Google Sheets updated
2. Also set up the webhook endpoint (Option 3) for real-time data retrieval when needed

This provides both cached data (in Google Sheets) and real-time data access through the API.

## Maintenance

- To update n8n: `docker-compose pull && docker-compose down && docker-compose up -d`
- To view logs: `docker-compose logs -f n8n`
- To stop n8n: `docker-compose down`

## Advantages of n8n Over Python Scraper

1. Visual workflow builder - easier to understand and modify
2. Built-in Gmail integration with OAuth
3. Easy to extend with additional nodes
4. No need to maintain custom regex code
5. Automatic retries and error handling
6. Scheduled workflow execution
7. Simplified deployment with Docker
8. Integration with various storage options (Google Sheets, databases, etc.)

## Connecting n8n API Workflow

The system now includes integration with n8n for fetching transaction data through the API endpoint. Follow these steps to set up the connection:

### Step 1: Start the n8n service

```bash
# Create the n8n data volume if it doesn't exist
docker volume create n8n_data

# Start the n8n service using Docker Compose
docker-compose up -d
```

### Step 2: Import the API Endpoint Workflow

1. Access n8n at `http://localhost:5678` in your browser
2. Sign in or create a new account if prompted
3. Click the three dots menu button (⋯) in the top-right
4. Select "Import from File..."
5. Browse and select the `Workflows/workflow2_api_endpoint.json` file
6. Click "Import" to load the workflow
7. After importing, you need to configure the Gmail credentials:
   - Click on the Gmail node and set up your Gmail OAuth credentials
   - Make note of the webhook URL for this workflow (it will be displayed at the top of the workflow)

### Step 3: Update the Transaction Fetcher

1. Open the `transaction_fetcher.py` file
2. Update the `N8N_WEBHOOK_URL` variable with the webhook URL from your imported workflow
   - It should look like: `http://localhost:5678/webhook/your-webhook-id`

### Step 4: Activate the Workflow

1. After configuring the credentials, click the "Save" button in the workflow
2. Toggle the "Active" switch to turn on the workflow

### Step 5: Test the Integration

1. Log in to the Flask application
2. On the dashboard, click the "Fetch from n8n API" button
3. The application will fetch transaction data from n8n using the webhook API

The n8n workflow will extract transaction data from your Gmail account, categorize it, and make it available via the API endpoint for the Flask application to consume.

## n8n Integration Feature

This application includes integration with n8n to fetch transaction data using a workflow API. The integration has been set up with the following components:

### How It Works

1. **n8n Workflow**: workflow2_api_endpoint.json provides an API that can fetch transaction data
2. **Flask Application**: The app includes an API endpoint that connects to the n8n API
3. **Dashboard Integration**: A "Fetch from n8n API" button has been added to the dashboard

### Step-by-Step Usage Instructions

#### 1. Start the n8n Service

```bash
# Create the n8n data volume (only needed first time)
docker volume create n8n_data

# Start the n8n service using Docker Compose
docker-compose up -d
```

#### 2. Import and Configure the Workflow

1. Access the n8n dashboard at http://localhost:5678
2. Create an account or log in
3. Click "Workflows" in the left sidebar
4. Click "Import from File" (or "Import from URL")
5. Select the file `Workflows/workflow2_api_endpoint.json`
6. After importing, click on the Gmail node to configure your Gmail credentials
7. Configure any other settings as needed (e.g., date ranges, filters)
8. Save and activate the workflow by toggling the "Active" switch in the top right

#### 3. Get the Webhook URL

1. In the n8n workflow editor, click on the "Webhook" node
2. Copy the displayed webhook URL
3. It should look something like: `http://localhost:5678/webhook-test/transactions`

#### 4. Update Your Application

1. Open `transaction_fetcher.py`
2. Update the `N8N_WEBHOOK_URL` variable with the webhook URL you copied
3. Save the file

#### 5. Test the Connection

Run the test script to check if your n8n API connection is working:

```bash
python test_n8n_connection.py
```

If successful, you should see transaction data retrieved from your Gmail account.

#### 6. Use the Feature in the Dashboard

1. Start the Flask application: `cd flask_app && python app.py`
2. Open your browser and navigate to http://localhost:5000
3. Log in to your account
4. On the dashboard, click the "Fetch from n8n API" button
5. The application will fetch transactions through the n8n workflow and display them on the dashboard

### Troubleshooting

If you encounter issues with the n8n integration:

1. **Check if n8n is running**: Run `docker ps` to verify the n8n container is active
2. **Verify webhook URL**: Make sure the URL in transaction_fetcher.py matches the one in your n8n webhook node
3. **Workflow activation**: Ensure your workflow is activated in n8n (toggle switch in top right)
4. **Gmail credentials**: Verify your Gmail credentials are correctly configured in the n8n workflow
5. **Check logs**: Look at both the Flask logs and n8n logs for error messages

### Further Customization

You can extend the n8n workflow to:
- Fetch data from other email providers
- Add more complex filtering logic
- Integrate with other services (e.g., banking APIs, expense tracking tools)
- Schedule automatic data synchronization

For more details on n8n workflows, visit the [n8n documentation](https://docs.n8n.io/).

### Important Note About n8n Webhook Test Mode

n8n webhooks work in two modes:

1. **Production Mode**: Activated by setting the workflow to "Active" using the toggle switch
2. **Test Mode**: Used for testing the webhook by clicking the "Test" button on the webhook node

In this project, we're using the **Test Mode** for simplicity, which has the following limitations:

- The webhook is only active for a short time after clicking the "Test" button
- Each time you want to use the webhook, you need to click "Test" again
- The webhook can only be used for ONE request after testing

#### How to Use the "Fetch from n8n API" Button:

1. Open n8n at http://localhost:5678
2. Navigate to your imported workflow2_api_endpoint workflow
3. Find the Webhook node (usually the first node)
4. Click the "Test" button on the Webhook node
5. Immediately return to your dashboard and click "Fetch from n8n API"

#### For Production Use:

If you want to use the webhook without repeatedly clicking "Test", you need to:

1. Open your workflow in n8n
2. Toggle the "Active" switch in the top-right corner to activate the workflow
3. The webhook will now be permanently active
4. Update the webhook URL in transaction_fetcher.py to remove the "-test" part:
   ```python
   N8N_WEBHOOK_URL = "http://localhost:5678/webhook/transactions"  # Remove -test
   ```

#### Troubleshooting Webhook Connection Issues:

If you see "No transactions found" or webhook errors:

1. Verify n8n is running: `docker ps | grep n8n`
2. Ensure the workflow is imported and configured correctly
3. Check if your Gmail credentials are set up in the Gmail node
4. For test mode, always click "Test" right before using the API
5. If using production mode, make sure the workflow is activated (toggle switch)
6. Verify the webhook URL in transaction_fetcher.py matches the URL shown in n8n 