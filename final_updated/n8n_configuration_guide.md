# n8n Configuration Guide for Transaction Fetching

This guide will help you properly configure n8n to work with the expense tracking application.

## Prerequisites

1. n8n running on your local machine or server (default: http://localhost:5678)
2. The `Transaction API Endpoint` workflow imported into n8n
3. Gmail account credentials configured in n8n

## Key Settings for the n8n Webhook

### Critical Settings for the Webhook Node

1. **Open your workflow** in n8n (Transaction API Endpoint workflow)
2. **Find the Webhook node** (typically the first node in the workflow)
3. **Configure the Webhook node**:
   - HTTP Method should be set to: `GET`
   - Path should be set to: `transactions` (**IMPORTANT**: Use exactly `transactions`, not "transactions-api")
   - Response mode should be: `Last Node` (VERY IMPORTANT - this must be "Last Node", not "Response Node")
   - The "Response Node" option causes the "Workflow was started" message issue
   - Make sure you've included a unique `webhookId` (should be set to `transactions`)

### Critical Settings for the Respond to Webhook Node

1. **REMOVE the Respond to Webhook node**. If your workflow has this node, delete it.
   - When "Response Mode" is set to "Last Node" in the Webhook, you don't need a Respond to Webhook node

2. **Most importantly**, ensure the last Function node (typically "Filter By Date") returns data in this format:
   ```javascript
   return [{ 
     json: { 
       transactions: [
         // Array of transaction objects
         { 
           transaction_id: "ABC123", 
           amount: 100.50, 
           recipient: "Merchant Name",
           status: "Completed",
           date: "2025-05-01"
           // other fields...
         },
         // More transactions...
       ],
       // Other optional data
       total: 5,
       timestamp: new Date().toISOString()
     }
   }];
   ```

## Proper Webhook URL

The correct webhook URL that your application uses is:
```
http://localhost:5678/webhook/transactions
```

Make sure that the webhook path in your n8n workflow matches exactly this URL path.

## Activating the Workflow

1. **Toggle the activate switch** in the top-right corner of the editor to activate the workflow
2. The workflow must be **active** for the production webhook URL to work properly
3. For testing, you can use the "Test" button on the Webhook node (but this only works for a single request)

## Testing Your Configuration

After configuring n8n, test the connection with the provided test scripts:

1. `python test_webhook_format.py` - Tests the webhook response format
2. `python transaction_fetcher.py` - Tests fetching transactions directly

## Troubleshooting

If you encounter issues:

1. **"Workflow was started" message instead of transaction data**
   - This is the most common issue
   - Solution: Change Webhook node's "Response Mode" from "Response Node" to "Last Node"
   - Remove any "Respond to Webhook" node from your workflow
   - Make sure the last Function node returns data in the correct format with a `transactions` array

2. **404 Error: "The requested webhook is not registered"**
   - Make sure your workflow is **activated** (toggle in top-right)
   - Verify the path in the Webhook node is set to `transactions`
   - For test mode, click the "Test" button on the Webhook node before making the request

3. **Empty transactions array**
   - Make sure your Gmail query is returning results
   - Check that the workflow properly extracts data from emails
   - Verify the Function node is correctly formatting the data with a transactions array

## URLs Used by the Application

The application tries the following webhook URLs in order:

1. `http://localhost:5678/webhook-test/transactions-api` (Test mode legacy format)
2. `http://localhost:5678/webhook/transactions-api` (Production mode legacy format)
3. `http://localhost:5678/webhook/transactions` (Current working format)

For best results, configure your n8n webhook with path `transactions`, not `transactions-api`. 