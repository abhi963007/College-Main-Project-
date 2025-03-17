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
    return render_template('index.html')

@app.route('/login.html', methods=['GET', 'POST'])
def login():
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
    
    # Get dashboard data from session if available
    dashboard_data = session.get('dashboard_data', {})
    
    # If we have dashboard data from categorized expenses
    if dashboard_data:
        # Pass the processed expense data to the template
        return render_template(
            'dashboard.html',
            user=user,
            expense_categories=dashboard_data.get('category_names', []),
            expense_values=dashboard_data.get('category_values', []),
            total_expenses=dashboard_data.get('total', 0),
            categorized_expenses=dashboard_data.get('expenses', [])
        )
    else:
        # If no data yet, just show the dashboard without expense data
        transactions = Transaction.query.order_by(Transaction.date.desc()).limit(10).all()
        return render_template('dashboard.html', user=user, transactions=transactions)

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

# Function to update progress status
def update_progress(status, percent):
    """Update the global progress status for tracking by the frontend"""
    global current_progress
    current_progress = {
        "status": status,
        "percent": percent,
        "progress": percent,  # Include both fields for compatibility
        "last_update": time.time()
    }
    logging.debug(f"Progress update: {status} - {percent}%")

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
        
        logging.info(f"Fetch data requested with force_refresh={force_refresh}")
        
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
            formatted_transactions.append({
                'date': tx.get('Date', datetime.now().strftime('%Y-%m-%d')),
                'amount': float(tx.get('Amount', 0)),
                'recipient': tx.get('Recipient', 'Unknown'),
                'txn_id': tx.get('Txn ID', ''),
                'txn_status': tx.get('Txn Status', ''),
                'payment_mode': tx.get('Payment Mode', ''),
                'type': tx.get('Type', '')
            })
        
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
                                    "recent_transactions": format_recent_transactions(formatted_transactions[:10])
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
                "recent_transactions": format_recent_transactions(formatted_transactions[:10])
            })
        
        update_progress("Processing complete!", 100)
        return jsonify({"status": "success", "message": "Data fetched successfully"})
    except Exception as e:
        logging.error(f"Error fetching data: {str(e)}", exc_info=True)
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
        if isinstance(expense, list) and len(expense) >= 3:
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
            'Food': ['restaurant', 'food', 'burger', 'pizza', 'cafe', 'eat', 'swiggy', 'zomato'],
            'Transport': ['uber', 'ola', 'cab', 'auto', 'taxi', 'petrol', 'fuel', 'bus', 'metro', 'train'],
            'Shopping': ['shop', 'store', 'market', 'mall', 'amazon', 'flipkart', 'myntra'],
            'Bills': ['bill', 'recharge', 'electricity', 'water', 'gas', 'internet', 'wifi', 'broadband'],
            'Entertainment': ['movie', 'theatre', 'game', 'netflix', 'prime', 'hotstar', 'subscription'],
            'Health': ['hospital', 'doctor', 'medical', 'medicine', 'pharmacy', 'clinic', 'health'],
            'Education': ['book', 'course', 'class', 'school', 'college', 'education', 'tuition'],
            'Personal': ['salon', 'spa', 'haircut', 'grooming'],
            'Home': ['rent', 'maintenance', 'repair', 'furniture', 'decor'],
            'Travel': ['flight', 'hotel', 'booking', 'holiday', 'vacation', 'trip'],
            'Tax': ['tax', 'gst', 'income tax', 'cess'],
            'Finance': ['emi', 'loan', 'interest', 'insurance', 'investment'],
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
            
        # Process each transaction
        categorized_transactions = []
        for tx in transactions:
            amount = float(tx.get('Amount', 0))
            recipient = tx.get('Recipient', '').lower()
            date = tx.get('Date', '')
            
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
        
        for expense in categorized_expenses:
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
            else:
                logging.warning(f"Invalid expense format: {expense}")
        
        # Calculate total
        total = sum(categories.values())
        
        # Create dashboard data
        dashboard_data = {
            'categories': categories,
            'category_names': list(categories.keys()),
            'category_values': list(categories.values()),
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

def format_recent_transactions(transactions):
    """Format recent transactions for display"""
    formatted_transactions = []
    for tx in transactions:
        formatted_transactions.append({
            'date': tx['date'],
            'amount': tx['amount'],
            'recipient': tx['recipient'],
            'txn_id': tx['txn_id'],
            'txn_status': tx['txn_status'],
            'payment_mode': tx['payment_mode'],
            'type': tx['type']
        })
    return formatted_transactions

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True) 