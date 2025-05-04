from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import subprocess
import sys
import os
import json
import re
import time
from datetime import datetime
import pandas as pd
import logging
import random
import traceback

# Configure logging with detailed file logging
log_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(log_dir, 'app.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

# Add the parent directory to sys.path to import from Gmail_Scrap
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Gmail_Scrap.scraper import main

# Import transaction fetcher
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from transaction_fetcher import fetch_transactions

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SECRET_KEY'] = 'your_secret_key_here'  # Change this to a secure secret key
db = SQLAlchemy(app)

# Global variable to track progress
current_progress = {
    "status": "Idle",
    "percent": 0,
    "last_update": time.time()
}

# Global variable to store categorized expenses
global_categorized_expenses = []

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    balance = db.Column(db.Float, nullable=False)

@app.route('/')
def home():
    # Check if user is already logged in
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    # Clear any flash messages when on home page
    session.pop('_flashes', None)
    return render_template('index.html')

@app.route('/login.html', methods=['GET', 'POST'])
def login():
    # Clear any existing flash messages when accessing login page directly
    if request.method == 'GET':
        session.pop('_flashes', None)
    
    # If user is already logged in, redirect to dashboard
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('pwd')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('pwd')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('login'))
            
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, email=email, password=hashed_password)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except:
            db.session.rollback()
            flash('An error occurred. Please try again.', 'error')
            
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    
    # Get current date for display
    current_date = datetime.now().strftime('%B %d, %Y')
    
    # Get dashboard data from session if available
    dashboard_data = session.get('dashboard_data', {})
    
    # Get transactions from database as fallback
    db_transactions = Transaction.query.order_by(Transaction.date.desc()).limit(10).all()
    
    # If we have dashboard data from categorized expenses
    if dashboard_data:
        # Get recent transactions from dashboard data
        recent_transactions = dashboard_data.get('recent_transactions', [])
        
        # If no recent transactions, try to use transactions from database
        if not recent_transactions:
            # Convert database transactions to dictionary format
            recent_transactions = [
                {
                    'date': str(tx.date),
                    'description': tx.description,
                    'category': tx.category,
                    'amount': tx.amount,
                    'balance': tx.balance
                }
                for tx in db_transactions
            ]
            
        # Pass the processed expense data to the template
        return render_template(
            'dashboard.html',
            user=user,
            current_date=current_date,
            expense_categories=dashboard_data.get('category_names', []),
            expense_values=dashboard_data.get('category_values', []),
            total_expenses=dashboard_data.get('total', 0),
            categorized_expenses=dashboard_data.get('expenses', []),
            transactions=recent_transactions
        )
    else:
        # If no data yet, just show the dashboard without expense data
        # Convert database transactions to dictionary format for display
        recent_transactions = [
            {
                'date': str(tx.date),
                'description': tx.description,
                'category': tx.category,
                'amount': tx.amount,
                'balance': tx.balance
            }
            for tx in db_transactions
        ]
        
        return render_template(
            'dashboard.html', 
            user=user,
            current_date=current_date,
            transactions=recent_transactions
        )

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

@app.route('/get_progress', methods=['GET'])
def get_progress():
    """Get the current progress status"""
    global current_progress
    return jsonify(current_progress)

@app.route('/api/n8n/transactions', methods=['GET'])
def get_n8n_transactions():
    """Get transactions using the n8n API workflow"""
    try:
        # Get date filters from request if any
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Update progress
        update_progress("Fetching transactions from n8n API...", 30)
        
        # Log the attempt
        app.logger.info(f"Fetching transactions from n8n API with date range: {start_date or 'all'} to {end_date or 'all'}")
        
        # Fetch transactions from n8n
        # Try both test mode and production mode
        transactions = fetch_transactions(start_date, end_date, test_mode=True)
        
        # Log the result
        app.logger.info(f"Fetched {len(transactions)} transactions from n8n API")
        
        # Update progress
        update_progress("Processing transactions...", 70)
        
        if not transactions:
            # Check if we got any error responses 
            import sys
            import io
            
            # Capture the stdout from fetch_transactions to see if there was an error message
            stdout_capture = io.StringIO()
            sys.stdout = stdout_capture
            
            # Call fetch_transactions again to get the error message
            fetch_transactions(start_date, end_date, test_mode=True)
            
            # Reset stdout
            sys.stdout = sys.__stdout__
            
            # Get the output
            captured_output = stdout_capture.getvalue()
            
            # Check for different types of errors
            if any(err in captured_output for err in ["webhook needs to be activated", "webhook is not registered", "WEBHOOK ERROR"]):
                update_progress("n8n webhook needs to be activated", 100)
                return jsonify({
                    "status": "warning", 
                    "message": "n8n webhook needs to be activated. Please open n8n (http://localhost:5678), navigate to your workflow, and click the 'Test' button on the Webhook node before trying again.",
                    "transaction_count": 0
                })
            elif "Invalid JSON response" in captured_output:
                update_progress("n8n returned invalid JSON", 100) 
                return jsonify({
                    "status": "warning", 
                    "message": "n8n webhook returned invalid JSON. Make sure the 'Respond to Webhook' node in n8n is configured to return JSON data with a 'transactions' array.",
                    "transaction_count": 0
                })
            else:
                update_progress("No transactions found", 100)
                return jsonify({
                    "status": "warning", 
                    "message": "No transactions found for the specified date range.",
                    "transaction_count": 0
                })
        
        # Process transactions
        processed_data = process_transactions(transactions)
        
        # Update progress
        update_progress("Completed successfully", 100)
        
        # Return data
        return jsonify({
            "status": "success",
            "message": f"Successfully fetched {len(transactions)} transactions",
            "transaction_count": len(transactions),
            "transactions": transactions,
            "total_expenses": processed_data.get("total_expenses", 0),
            "expense_categories": processed_data.get("expense_categories", []),
            "expense_values": processed_data.get("expense_values", []),
            "categorized_expenses": processed_data.get("categorized_expenses", []),
            "recent_transactions": processed_data.get("recent_transactions", []),
            "monthly_data": processed_data.get("monthly_data", {})
        })
    
    except Exception as e:
        # Log the error
        app.logger.error(f"Error fetching transactions from n8n API: {str(e)}")
        app.logger.error(traceback.format_exc())
        
        # Update progress to indicate error
        update_progress("Error fetching transactions", 100)
        
        # Return error response
        return jsonify({
            "status": "error",
            "message": f"Error fetching transactions: {str(e)}",
            "transaction_count": 0
        }), 500

def process_transactions(transactions):
    """Process transactions into a format for the dashboard"""
    try:
        # Calculate total expenses
        total_expenses = sum(float(tx.get('amount', 0)) for tx in transactions)
        
        # Count transactions by category
        categories = {}
        for tx in transactions:
            category = tx.get('category', 'Uncategorized')
            if category in categories:
                categories[category] += float(tx.get('amount', 0))
            else:
                categories[category] = float(tx.get('amount', 0))
        
        # Sort categories by amount
        sorted_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)
        
        # Extract category names and values
        expense_categories = [cat for cat, amount in sorted_categories]
        expense_values = [amount for cat, amount in sorted_categories]
        
        # Format categorized expenses for table
        categorized_expenses = [
            {"category": cat, "amount": amount, "percentage": (amount / total_expenses * 100) if total_expenses > 0 else 0}
            for cat, amount in sorted_categories
        ]
        
        # Get recent transactions (last 10)
        recent_transactions = sorted(transactions, key=lambda x: x.get('date', ''), reverse=True)[:10]
        
        # Group by month for trend chart
        monthly_data = {}
        for tx in transactions:
            date_str = tx.get('date', '')
            if date_str:
                try:
                    # Extract month from date
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                    month_key = date_obj.strftime("%b %Y")
                    
                    if month_key in monthly_data:
                        monthly_data[month_key] += float(tx.get('amount', 0))
                    else:
                        monthly_data[month_key] = float(tx.get('amount', 0))
                except Exception as e:
                    app.logger.warning(f"Error parsing date '{date_str}': {str(e)}")
        
        # Return processed data
        return {
            "total_expenses": total_expenses,
            "expense_categories": expense_categories,
            "expense_values": expense_values,
            "categorized_expenses": categorized_expenses,
            "recent_transactions": recent_transactions,
            "monthly_data": monthly_data
        }
        
    except Exception as e:
        app.logger.error(f"Error processing transactions: {str(e)}")
        app.logger.error(traceback.format_exc())
        return {}

# Function to update progress status
def update_progress(status, percentage):
    """Update the global progress status for tracking by the frontend"""
    global current_progress
    current_progress = {
        "status": status,
        "percentage": percentage,
        "last_update": time.time()
    }
    app.logger.debug(f"Progress update: {status} - {percentage}%")

@app.route('/fetch_data', methods=['POST'])
def fetch_data():
    try:
        # Parse request data
        data = request.json if request.is_json else request.form
        
        # Handle force_refresh whether it's a string or boolean
        force_refresh_param = data.get('force_refresh', 'true')
        if isinstance(force_refresh_param, bool):
            force_refresh = force_refresh_param
        else:
            force_refresh = str(force_refresh_param).lower() == 'true'
        
        # Get date range parameters
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        logging.info(f"Fetch data requested with force_refresh={force_refresh}, start_date={start_date}, end_date={end_date}")
        
        # Reset progress for new request
        update_progress("Initializing Gmail scraper...", 5)
        
        # Import the scraper and run it
        from Gmail_Scrap import scraper
        
        logging.info("Starting Gmail scraper...")
        
        # Run the scraper with a progress callback
        transactions = scraper.main(force_refresh=force_refresh, progress_callback=update_progress)
        
        if not transactions:
            update_progress("No transactions found", 100)
            return jsonify({"status": "error", "message": "No transactions found"})
        
        logging.info(f"Scraper returned {len(transactions)} transactions")
        update_progress(f"Processing {len(transactions)} transactions for categorization...", 80)
        
        # Process and format the transaction data for consistency
        formatted_transactions = []
        for tx in transactions:
            # Ensure date is properly formatted for filtering
            date_str = tx.get('Date', datetime.now().strftime('%Y-%m-%d'))
            # Try to handle different date formats
            try:
                # If date is not in YYYY-MM-DD format, try to parse and convert it
                if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
                    # Try common date formats
                    for fmt in ['%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%m-%d-%Y', '%Y/%m/%d']:
                        try:
                            date_obj = datetime.strptime(date_str, fmt)
                            date_str = date_obj.strftime('%Y-%m-%d')
                            break
                        except ValueError:
                            continue
            except Exception as e:
                logging.warning(f"Could not parse date '{date_str}': {str(e)}")
                # Use current date if parsing fails
                date_str = datetime.now().strftime('%Y-%m-%d')
                
            # Ensure amount is a valid float
            try:
                amount = float(tx.get('Amount', 0))
            except (ValueError, TypeError):
                amount = 0
                
            formatted_tx = {
                'date': date_str,
                'amount': amount,
                'recipient': tx.get('Recipient', 'Unknown'),
                'txn_id': tx.get('Txn ID', ''),
                'txn_status': tx.get('Txn Status', ''),
                'payment_mode': tx.get('Payment Mode', ''),
                'type': tx.get('Type', '')
            }
            formatted_transactions.append(formatted_tx)
        
        # Filter transactions by date range if provided
        original_count = len(formatted_transactions)
        if start_date and end_date:
            try:
                start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                
                # Filter transactions that fall within the date range
                filtered_transactions = []
                for tx in formatted_transactions:
                    try:
                        tx_date = datetime.strptime(tx['date'], '%Y-%m-%d')
                        if start_date_obj <= tx_date <= end_date_obj:
                            filtered_transactions.append(tx)
                        else:
                            logging.debug(f"Filtered out transaction from {tx['date']} - outside date range")
                    except (ValueError, TypeError) as e:
                        logging.warning(f"Error parsing date '{tx['date']}': {str(e)}")
                        # Include transactions with invalid dates if we can't determine if they're in range
                        filtered_transactions.append(tx)
                
                logging.info(f"Filtered {len(filtered_transactions)} transactions from {original_count} based on date range")
                formatted_transactions = filtered_transactions
            except (ValueError, TypeError) as e:
                logging.error(f"Error parsing date range: {str(e)}")
                # Continue with unfiltered transactions
        
        # Try to use the model for categorization
        try:
            # Import and run the expense categorization
            from model import init
            
            # Log that we're starting expense categorization
            logging.info(f"Starting expense categorization for {len(formatted_transactions)} transactions")
            
            # Pass the transactions directly to the model
            categorized_expenses = init.main(transactions=formatted_transactions, progress_callback=update_progress)
            
            # After model processing, check if the JSON file exists
            json_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'model', 'categorized_expenses.json')
            
            # Try to read the file with retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if os.path.exists(json_file_path):
                        with open(json_file_path, 'r') as f:
                            categorized_data = json.load(f)
                            if 'expenses' in categorized_data and categorized_data['expenses']:
                                categorized_expenses = categorized_data['expenses']
                                logging.info(f"Loaded {len(categorized_expenses)} categorized expenses from file")
                                
                                # Process and store in session for dashboard display
                                send_to_dashboard(categorized_expenses)
                                
                                # Get the dashboard data from session
                                dashboard_data = session.get('dashboard_data', {})
                                
                                # Return the processed data for immediate display
                                return jsonify({
                                    "status": "success",
                                    "message": "Data fetched successfully",
                                    "expense_categories": dashboard_data.get('category_names', []),
                                    "expense_values": dashboard_data.get('category_values', []),
                                    "total_expenses": dashboard_data.get('total', 0),
                                    "categorized_expenses": dashboard_data.get('expenses', []),
                                    "transaction_count": len(categorized_expenses),
                                    "monthly_data": generate_monthly_data(dashboard_data.get('total', 0)),
                                    "recent_transactions": format_recent_transactions(formatted_transactions, limit=10),
                                    "date_range": {"start_date": start_date, "end_date": end_date} if start_date and end_date else None
                                })
                                
                except Exception as e:
                    logging.error(f"Error loading categorized expenses from file (attempt {attempt + 1}): {str(e)}")
                    if attempt < max_retries - 1:
                        time.sleep(1)  # Wait before retrying
                        continue
                    raise
            
        except Exception as model_error:
            logging.error(f"Error in model categorization: {str(model_error)}", exc_info=True)
            update_progress(f"Using basic categorization due to model error: {str(model_error)}", 85)
            
            # Create a basic version of categorized expenses
            categorized_expenses = []
            for tx in formatted_transactions:
                # Check what category this might belong to based on recipient name
                recipient = tx.get('recipient', '').lower()
                
                # Determine category based on keywords
                category = 'Extra'  # Default category
                
                # Simple rules for categorization
                if any(word in recipient for word in ['food', 'restaurant', 'cafe', 'pizza']):
                    category = 'Food'
                elif any(word in recipient for word in ['uber', 'ola', 'cab', 'auto', 'petrol']):
                    category = 'Transport'
                elif any(word in recipient for word in ['amazon', 'flipkart', 'shop']):
                    category = 'Shopping'
                elif any(word in recipient for word in ['tax', 'bill', 'insurance']):
                    category = 'Home & Tax'
                elif any(word in recipient for word in ['doctor', 'hospital', 'medicine']):
                    category = 'Health'
                
                categorized_expenses.append({
                    'description': tx.get('recipient', 'Unknown'),
                    'category': category,
                    'amount': float(tx.get('amount', 0))
                })
            
            # Process and store in session
            send_to_dashboard(categorized_expenses)
            
            # Get the dashboard data from session
            dashboard_data = session.get('dashboard_data', {})
            
            # Return the processed data for immediate display
            return jsonify({
                "status": "success",
                "message": "Data fetched successfully",
                "expense_categories": dashboard_data.get('category_names', []),
                "expense_values": dashboard_data.get('category_values', []),
                "total_expenses": dashboard_data.get('total', 0),
                "categorized_expenses": dashboard_data.get('expenses', []),
                "transaction_count": len(categorized_expenses),
                "monthly_data": generate_monthly_data(dashboard_data.get('total', 0)),
                "recent_transactions": format_recent_transactions(formatted_transactions, limit=10),
                "date_range": {"start_date": start_date, "end_date": end_date} if start_date and end_date else None
            })
        
        update_progress("Processing complete!", 100)
        return jsonify({"status": "success", "message": "Data fetched successfully"})
    except Exception as e:
        logging.error(f"Error fetching data: {str(e)}", exc_info=True)
        update_progress(f"Error: {str(e)}", 100)
        return jsonify({"status": "error", "message": f"Error: {str(e)}"})

@app.route('/fetch_n8n_data', methods=['POST'])
def fetch_n8n_data():
    """Fetch transaction data from n8n API and display on dashboard"""
    try:
        # Parse request data
        data = request.json if request.is_json else request.form
        
        # Get date range parameters
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        logging.info(f"Fetch n8n data requested with start_date={start_date}, end_date={end_date}")
        
        # Reset progress for new request
        update_progress("Initializing n8n transaction fetch...", 5)
        
        # Fetch transactions from n8n using PRODUCTION mode
        # This will use the activated workflow instead of test mode
        transactions = fetch_transactions(start_date, end_date, test_mode=False)
        
        # Log the raw transactions for debugging
        logging.info(f"Raw n8n response: {json.dumps(transactions, indent=2)[:1000]}...")
        
        if not transactions:
            update_progress("No transactions found", 100)
            return jsonify({
                "status": "warning", 
                "message": "No transactions found for the specified date range. Make sure your n8n workflow is ACTIVATED.",
                "transaction_count": 0
            })
        
        logging.info(f"n8n API returned {len(transactions)} transactions")
        update_progress(f"Processing {len(transactions)} transactions for categorization...", 80)
        
        # Process transactions for dashboard display
        processed_data = process_transactions(transactions)
        
        # Update progress
        update_progress("Completed successfully", 100)
        
        # Return the processed data for immediate display
        return jsonify({
            "status": "success",
            "message": f"Successfully fetched {len(transactions)} transactions from n8n",
            "expense_categories": processed_data.get("expense_categories", []),
            "expense_values": processed_data.get("expense_values", []),
            "total_expenses": processed_data.get("total_expenses", 0),
            "categorized_expenses": processed_data.get("categorized_expenses", []),
            "transaction_count": len(transactions),
            "monthly_data": processed_data.get("monthly_data", {}),
            "recent_transactions": processed_data.get("recent_transactions", [])
        })
        
    except Exception as e:
        logging.error(f"Error fetching data from n8n: {str(e)}", exc_info=True)
        update_progress(f"Error: {str(e)}", 100)
        return jsonify({"status": "error", "message": f"Error: {str(e)}"})

def process_categorized_expenses(categorized_expenses):
    """Process categorized expenses for dashboard display"""
    global current_progress
    
    app.logger.info("Processing categorized expenses for dashboard")
    
    # Initialize data structures
    categories = {}
    categorized_expenses_formatted = []
    
    # Process each expense
    for expense in categorized_expenses:
        if isinstance(expense, dict):
            # Handle dict format (direct from categorized_expenses.json)
            category = expense.get('category', 'Other')
            try:
                amount = float(expense.get('amount', 0))
                categories[category] = categories.get(category, 0) + amount
                
                # Format the expense for the table
                categorized_expenses_formatted.append({
                    'description': str(expense.get('recipient', 'Unknown')),
                    'category': category,
                    'amount': amount
                })
            except (ValueError, TypeError) as e:
                app.logger.warning(f"Invalid amount in expense {expense}: {str(e)}")
        elif isinstance(expense, list) and len(expense) >= 3:
            # Handle list format (from ollama model)
            category = expense[1]
            try:
                amount = float(expense[2])
                categories[category] = categories.get(category, 0) + amount
                
                # Format the expense for the table
                categorized_expenses_formatted.append({
                    'description': str(expense[0]),
                    'category': str(expense[1]),
                    'amount': float(expense[2])
                })
            except (ValueError, TypeError) as e:
                app.logger.warning(f"Invalid amount in expense {expense}: {str(e)}")
    
    # Prepare data for charts
    expense_categories = list(categories.keys())
    expense_values = list(categories.values())
    
    # Calculate total expenses
    total_expenses = sum(expense_values)
    app.logger.info(f"Total expenses: {total_expenses}")
    
    # Generate monthly data for the spending trend
    months = ["Jan", "Feb", "Mar", "Apr", "May"]
    monthly_data = []
    
    # Create a simple trend based on total expenses
    monthly_avg = total_expenses / len(months) if len(months) > 0 else 0
    for _ in months:
        # Add some random variation
        variation = 0.8 + (0.4 * random.random())
        monthly_data.append(round(monthly_avg * variation))
    
    app.logger.info("Successfully prepared data for dashboard")
    
    # Update progress to completed
    current_progress = {
        "progress": 100,
        "status": "Completed",
        "last_update": time.time()
    }
    
    return {
        "expense_categories": expense_categories,
        "expense_values": expense_values,
        "total_expenses": total_expenses,
        "categorized_expenses": categorized_expenses_formatted,
        "months": months,
        "monthly_data": monthly_data
    }

def create_basic_categorization(transactions):
    """Create a basic categorization if the model fails"""
    try:
        # If no transactions, return empty result
        if not transactions:
            return {}
            
        # Simple categories based on keywords in recipient
        categories = {
            'Food': ['restaurant', 'food', 'burger', 'pizza', 'cafe', 'eat', 'swiggy', 'zomato', 'strawberry', 'pranavam'],
            'Transport': ['uber', 'ola', 'cab', 'auto', 'taxi', 'petrol', 'fuel', 'bus', 'metro', 'train', 'parivaram'],
            'Shopping': ['shop', 'store', 'market', 'mall', 'amazon', 'flipkart', 'myntra', 'toy'],
            'Bills': ['bill', 'recharge', 'electricity', 'water', 'gas', 'internet', 'wifi', 'broadband', 'google', 'hostinger'],
            'Entertainment': ['movie', 'theatre', 'game', 'netflix', 'prime', 'hotstar', 'subscription', 'unipin', 'friends'],
            'Health': ['hospital', 'doctor', 'medical', 'medicine', 'pharmacy', 'clinic', 'health'],
            'Education': ['book', 'course', 'class', 'school', 'college', 'education', 'tuition'],
            'Personal': ['person', 'friend', 'transfer', 'borrow', 'lend', 'pay', 'anujith', 'abin', 'renjith', 'aswin'],
            'Home & Tax': ['rent', 'maintenance', 'repair', 'furniture', 'decor', 'tax', 'insurance', 'policybazaar', 'icici'],
            'Travel': ['flight', 'hotel', 'booking', 'holiday', 'vacation', 'trip'],
            'Extra': ['unknown', 'misc', 'other']
        }
        
        # Initialize result
        result = {
            'total_expense': 0,
            'monthly_average': 0,
            'transaction_count': len(transactions),
            'top_category': '',
            'categories': {},
            'monthly_data': {},
            'transactions': []
        }
        
        # Initialize categories with 0 values
        for category in categories:
            result['categories'][category] = 0
            
        # Also initialize 'Other' category
        result['categories']['Other'] = 0
            
        # Process each transaction
        categorized_transactions = []
        for tx in transactions:
            amount = float(tx.get('amount', 0))
            recipient = tx.get('recipient', '').lower()
            date = tx.get('date', '')
            
            # Skip invalid transactions
            if amount <= 0 or not recipient or not date:
                continue
                
            # Determine category based on keywords
            assigned_category = 'Other'
            for category, keywords in categories.items():
                if any(keyword.lower() in recipient.lower() for keyword in keywords):
                    assigned_category = category
                    break
            
            # Update category total
            if assigned_category not in result['categories']:
                result['categories'][assigned_category] = 0
            result['categories'][assigned_category] += amount
            
            # Add to transactions list
            categorized_transactions.append({
                'amount': amount,
                'recipient': recipient,
                'date': date,
                'category': assigned_category
            })
            
            # Update monthly data
            try:
                # Try to parse the date to extract month
                date_obj = datetime.strptime(date, '%Y-%m-%d')
                month_key = date_obj.strftime('%Y-%m')
                
                if month_key not in result['monthly_data']:
                    result['monthly_data'][month_key] = 0
                result['monthly_data'][month_key] += amount
            except:
                # If date parsing fails, use 'Unknown' as month
                if 'Unknown' not in result['monthly_data']:
                    result['monthly_data']['Unknown'] = 0
                result['monthly_data']['Unknown'] += amount
        
        # Calculate total expense
        result['total_expense'] = sum(result['categories'].values())
        
        # Calculate monthly average
        if len(result['monthly_data']) > 0:
            result['monthly_average'] = result['total_expense'] / len(result['monthly_data'])
        
        # Determine top category
        if result['categories']:
            result['top_category'] = max(result['categories'].items(), key=lambda x: x[1])[0]
        
        # Add categorized transactions to result
        result['transactions'] = categorized_transactions
        
        return result
    except Exception as e:
        app.logger.error(f"Error creating basic categorization: {str(e)}")
        return {}

def send_to_dashboard(categorized_expenses):
    """Save categorized expenses to the session for display on the dashboard"""
    try:
        # Log the incoming data for debugging
        logging.info(f"Processing {len(categorized_expenses)} categorized expenses for dashboard display")
        
        # Process the expenses for dashboard display
        categories = {}
        expense_details = []
        
        # Check what format the categorized_expenses are in (list or dictionary)
        for expense in categorized_expenses:
            # Handle list format from the model output: [description, category, amount]
            if isinstance(expense, list) and len(expense) >= 3:
                description = str(expense[0])
                category = str(expense[1])
                try:
                    amount = float(expense[2])
                    
                    # Aggregate by category
                    if category in categories:
                        categories[category] += amount
                    else:
                        categories[category] = amount
                    
                    # Add to expense details list
                    expense_details.append({
                        'description': description,
                        'category': category,
                        'amount': amount
                    })
                except (ValueError, TypeError) as e:
                    logging.warning(f"Invalid amount in expense {expense}: {str(e)}")
            
            # Handle dictionary format from other sources
            elif isinstance(expense, dict):
                description = str(expense.get('description', expense.get('recipient', 'Unknown')))
                category = str(expense.get('category', 'Other'))
                try:
                    amount = float(expense.get('amount', 0))
                    
                    # Aggregate by category
                    if category in categories:
                        categories[category] += amount
                    else:
                        categories[category] = amount
                    
                    # Add to expense details list
                    expense_details.append({
                        'description': description,
                        'category': category,
                        'amount': amount
                    })
                except (ValueError, TypeError) as e:
                    logging.warning(f"Invalid amount in expense {expense}: {str(e)}")
            else:
                logging.warning(f"Invalid expense format: {expense}")
        
        # Calculate total
        total = sum(categories.values())
        
        # Sort categories by value (highest to lowest)
        sorted_categories = dict(sorted(categories.items(), key=lambda item: item[1], reverse=True))
        
        # Create dashboard data
        dashboard_data = {
            'categories': sorted_categories,
            'category_names': list(sorted_categories.keys()),
            'category_values': list(sorted_categories.values()),
            'expenses': expense_details,
            'total': total
        }
        
        # Log the processed data
        logging.info(f"Processed data: {len(expense_details)} expenses in {len(categories)} categories")
        logging.info(f"Categories: {list(categories.keys())}")
        logging.info(f"Total amount: {total}")
        
        # Store in session
        session['dashboard_data'] = dashboard_data
        
        logging.info("Successfully stored dashboard data in session")
        return True
    except Exception as e:
        logging.error(f"Error processing categorized expenses: {str(e)}", exc_info=True)
        return False

def generate_monthly_data(total_expenses):
    """Generate monthly data for the spending trend"""
    months = ["Jan", "Feb", "Mar", "Apr", "May"]
    monthly_data = []
    
    # Create a simple trend based on total expenses
    monthly_avg = total_expenses / len(months) if len(months) > 0 else 0
    for _ in months:
        # Add some random variation
        variation = 0.8 + (0.4 * random.random())
        monthly_data.append(round(monthly_avg * variation))
    
    return monthly_data

def format_recent_transactions(transactions, limit=None):
    """Format recent transactions for display
    
    Args:
        transactions: List of transaction dictionaries
        limit: Optional limit on number of transactions to return (default: return all)
    
    Returns:
        List of formatted transaction dictionaries
    """
    formatted_transactions = []
    
    # Sort transactions by date (most recent first)
    sorted_transactions = sorted(
        transactions, 
        key=lambda x: x.get('date', '0000-00-00'),
        reverse=True
    )
    
    # Apply limit if specified
    if limit and isinstance(limit, int) and limit > 0:
        transactions_to_format = sorted_transactions[:limit]
    else:
        transactions_to_format = sorted_transactions
    
    # Format each transaction
    for tx in transactions_to_format:
        try:
            # Ensure date is formatted correctly
            date_str = tx.get('date', '')
            
            # Format amount to ensure it's a float
            try:
                amount = float(tx.get('amount', 0))
            except (ValueError, TypeError):
                amount = 0
            
            formatted_transactions.append({
                'date': date_str,
                'amount': amount,
                'recipient': tx.get('recipient', 'Unknown'),
                'description': tx.get('recipient', 'Unknown'),  # Add description for dashboard display
                'category': tx.get('category', 'Other'),        # Add category if available
                'txn_id': tx.get('txn_id', ''),
                'txn_status': tx.get('txn_status', ''),
                'payment_mode': tx.get('payment_mode', ''),
                'type': tx.get('type', '')
            })
        except Exception as e:
            logging.warning(f"Error formatting transaction: {str(e)}")
            # Skip problematic transactions
            continue
            
    return formatted_transactions

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True) 