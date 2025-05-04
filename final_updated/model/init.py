import yaml
import json
import ollama
from .error_handler import ExpenseTrackerError, display_error_and_exit
from .read_keep import read_keep_notes
from .write_sheets import write_to_sheet
from halo import Halo
import pandas as pd
import matplotlib.pyplot as plt
import os
import requests
import subprocess
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import hashlib
import pickle
import argparse
from datetime import datetime
import re

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), 'expense_tracker.log')),
        logging.StreamHandler()
    ]
)

# Cache directory
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# Flag to track if we've already tried to start Ollama
tried_starting_ollama = False

def load_categories():
    """Load categories from the YAML file with fallback paths"""
    possible_paths = [
        os.path.join(os.path.dirname(__file__), 'categories.yaml'),
        os.path.join(os.path.dirname(__file__), 'config', 'categories.yaml'),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), 'model', 'categories.yaml')
    ]
    
    for path in possible_paths:
        try:
            if os.path.exists(path):
                with open(path, 'r') as file:
                    data = yaml.safe_load(file)
                return data['categories']
        except Exception as e:
            logging.warning(f"Failed to load categories from {path}: {e}")
    
    # If no file is found, return a default set of categories
    logging.warning("Using default categories as no categories.yaml was found")
    return [
        {"name": "Food", "description": "Restaurants, groceries, food delivery"},
        {"name": "Transport", "description": "Uber, taxi, auto, fuel, public transport"},
        {"name": "Shopping", "description": "Clothes, electronics, online shopping"},
        {"name": "Bills", "description": "Electricity, water, internet, mobile recharge"},
        {"name": "Entertainment", "description": "Movies, games, subscriptions"},
        {"name": "Health", "description": "Medical, fitness, pharmacy"},
        {"name": "Education", "description": "Books, courses, tuition"},
        {"name": "Home & Tax", "description": "Rent, maintenance, repairs, taxes"},
        {"name": "Extra", "description": "Miscellaneous expenses"}
    ]

def load_prompt_template():
    """Load prompt template with fallback paths"""
    possible_paths = [
        os.path.join(os.path.dirname(__file__), 'prompt_template.txt'),
        os.path.join(os.path.dirname(__file__), 'config', 'prompt_template.txt'),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), 'model', 'prompt_template.txt')
    ]
    
    for path in possible_paths:
        try:
            if os.path.exists(path):
                with open(path, 'r') as file:
                    return file.read()
        except Exception as e:
            logging.warning(f"Failed to load prompt template from {path}: {e}")
    
    # If no file is found, return a default prompt template
    logging.warning("Using default prompt template as no prompt_template.txt was found")
    return """
    Please categorize the following expenses into appropriate categories:
    
    Expenses:
    {expenses}
    
    Available categories:
    {categories}
    
    Return the results in JSON format where each expense has a 'description' and 'category' field.
    """

def get_cache_key(expenses_batch):
    """Generate a unique cache key for a batch of expenses"""
    expense_str = json.dumps(expenses_batch, sort_keys=True)
    return hashlib.md5(expense_str.encode()).hexdigest()

def get_cached_results(cache_key):
    """Try to get cached results"""
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.pkl")
    if os.path.exists(cache_file):
        # Check if cache is less than 24 hours old
        if time.time() - os.path.getmtime(cache_file) < 86400:  # 24 hours
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
    return None

def save_to_cache(cache_key, results):
    """Save results to cache"""
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.pkl")
    with open(cache_file, 'wb') as f:
        pickle.dump(results, f)

def fallback_categorize_expense(expense, categories):
    """Simple rule-based categorization when Ollama is not available"""
    description = expense['description'].lower()
    
    # Define keywords for each category
    category_keywords = {}
    for cat in categories:
        category_name = cat['name']
        keywords = cat['description'].lower().split(',')
        category_keywords[category_name] = keywords
    
    # Add some common keywords for each category
    common_keywords = {
        'Food': ['restaurant', 'food', 'cafe', 'pizza', 'burger', 'meal', 'lunch', 'dinner', 'breakfast', 'bakery', 'grocery'],
        'Transport': ['uber', 'ola', 'taxi', 'cab', 'auto', 'bus', 'train', 'metro', 'petrol', 'diesel', 'fuel', 'parking'],
        'Shopping': ['amazon', 'flipkart', 'myntra', 'store', 'mall', 'shop', 'purchase', 'buy'],
        'Bills': ['bill', 'payment', 'electricity', 'water', 'gas', 'internet', 'wifi', 'broadband', 'recharge', 'mobile'],
        'Entertainment': ['movie', 'theatre', 'cinema', 'concert', 'show', 'game', 'netflix', 'prime', 'hotstar', 'subscription'],
        'Health': ['hospital', 'doctor', 'medicine', 'medical', 'pharmacy', 'health', 'clinic', 'dental', 'fitness'],
        'Education': ['school', 'college', 'university', 'course', 'class', 'tuition', 'book', 'stationery'],
        'Home & Tax': ['rent', 'maintenance', 'repair', 'furniture', 'appliance', 'tax', 'insurance', 'emi', 'loan'],
        'Extra': ['gift', 'donation', 'charity', 'other', 'miscellaneous']
    }
    
    # Merge common keywords with category keywords
    for category, keywords in common_keywords.items():
        if category in category_keywords:
            category_keywords[category].extend(keywords)
    
    # Check for matches
    for category, keywords in category_keywords.items():
        for keyword in keywords:
            if keyword in description:
                return category
    
    # Default category if no match found
    return "Extra"

def check_ollama_running():
    """Check if Ollama server is running"""
    global tried_starting_ollama
    
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        if response.status_code == 200:
            logging.info("Ollama server is already running")
            return True
        else:
            if not tried_starting_ollama:
                logging.warning(f"Ollama server returned unexpected status code: {response.status_code}")
            return False
    except requests.exceptions.RequestException:
        if not tried_starting_ollama:
            logging.warning("Ollama server is not running")
        return False

def start_ollama():
    """Since Ollama should already be running as a service, this function now just checks and logs status"""
    global tried_starting_ollama
    
    if tried_starting_ollama:
        return False
        
    tried_starting_ollama = True
    
    # Just check if Ollama is accessible
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        if response.status_code == 200:
            logging.info("Successfully connected to Ollama server")
            return True
        else:
            logging.error(f"Ollama server returned unexpected status code: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Could not connect to Ollama server: {str(e)}")
        return False

def categorize_expense_batch(batch, categories, prompt_template, force_recategorize=False):
    """Categorize a batch of expenses"""
    try:
        # Generate cache key for this batch
        cache_key = get_cache_key(batch)
        
        # Only use cache if not forcing recategorization
        if not force_recategorize:
            cached_results = get_cached_results(cache_key)
            if cached_results:
                logging.info(f"Using cached results for batch with key {cache_key[:8]}")
                return cached_results
        
        # Format categories string
        categories_str = "\n".join(f"- {cat['name']}: {cat['description']}" for cat in categories)
        
        # Convert batch to simpler format for the model
        simplified_batch = []
        for expense in batch:
            simplified_batch.append({
                "description": str(expense['description']),
                "amount": float(expense['amount'])
            })
        
        # Create the prompt with simplified batch
        batch_str = json.dumps(simplified_batch, ensure_ascii=False)
        
        # Log the prompt for debugging
        logging.debug(f"Sending prompt to model: {batch_str[:200]}...")
        
        # Ensure Ollama is running
        ollama_available = check_ollama_running()
        if not ollama_available:
            ollama_available = start_ollama()
        
        if ollama_available:
            # Try multiple times in case of connection issues
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # Make the API call with timeout
                    start_time = time.time()
                    response = ollama.chat(
                        model='llama3', 
                        messages=[{
                            "role": "user", 
                            "content": prompt_template.format(expenses=batch_str, categories=categories_str)
                        }],
                        options={
                            "temperature": 0.1,
                            "num_predict": 256,
                            "top_k": 10,
                            "top_p": 0.9
                        }
                    )
                    
                    processing_time = time.time() - start_time
                    logging.info(f"Ollama processing time: {processing_time:.2f} seconds")
                    
                    # Extract the categorized expenses from the response
                    content = response['message']['content']
                    
                    # Try to parse the JSON response
                    try:
                        # Find JSON in the response
                        json_match = re.search(r'```json\n(.*?)\n```', content, re.DOTALL)
                        if json_match:
                            json_str = json_match.group(1)
                        else:
                            # Try to find any JSON-like structure
                            json_match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
                            if json_match:
                                json_str = json_match.group(0)
                            else:
                                json_str = content
                        
                        categorized_expenses = json.loads(json_str)
                        
                        # Validate the structure
                        if not isinstance(categorized_expenses, list):
                            raise ValueError("Response is not a list")
                        
                        # Convert to the expected format
                        results = []
                        for i, expense in enumerate(categorized_expenses):
                            if isinstance(expense, dict) and 'description' in expense and 'category' in expense:
                                results.append([
                                    expense['description'],
                                    expense['category'],
                                    batch[i]['amount']
                                ])
                            else:
                                logging.warning(f"Invalid expense format in response: {expense}")
                                # Use fallback for this expense
                                results.append([
                                    batch[i]['description'],
                                    fallback_categorize_expense(batch[i], categories),
                                    batch[i]['amount']
                                ])
                        
                        # Cache the results
                        save_to_cache(cache_key, results)
                        return results
                        
                    except (json.JSONDecodeError, ValueError) as e:
                        logging.error(f"Error parsing model response: {str(e)}")
                        logging.debug(f"Raw response: {content[:500]}...")
                        
                        if attempt < max_retries - 1:
                            logging.info(f"Retrying batch processing (attempt {attempt+2}/{max_retries})...")
                            continue
                        else:
                            raise ValueError(f"Failed to parse model response after {max_retries} attempts")
                
                except Exception as e:
                    if attempt < max_retries - 1:
                        logging.warning(f"Ollama connection error: {str(e)}. Retrying in 2 seconds...")
                        time.sleep(2)
                        continue
                    else:
                        logging.error(f"Ollama failed after {max_retries} attempts: {str(e)}")
                        raise
        
        # If Ollama is not available or all retries failed, use fallback
        logging.info("Using fallback categorization method")
        results = []
        for expense in batch:
            category = fallback_categorize_expense(expense, categories)
            results.append([expense['description'], category, expense['amount']])
        
        # Cache the results
        save_to_cache(cache_key, results)
        return results
            
    except Exception as e:
        logging.error(f"Batch processing error: {str(e)}")
        # Use fallback categorization
        logging.info("Using fallback categorization method due to error")
        results = []
        for expense in batch:
            category = fallback_categorize_expense(expense, categories)
            results.append([expense['description'], category, expense['amount']])
        return results

def categorize_expenses(expenses, categories, spinner=None, force_recategorize=False, progress_callback=None):
    """Categorize expenses using the Ollama API"""
    # Check if expenses is a valid list
    if not expenses or not isinstance(expenses, list):
        logging.error("Invalid expenses list")
        return []
    
    # Helper function to update progress
    def update_progress(status, percent):
        if progress_callback:
            try:
                progress_callback(status, percent)
            except Exception as e:
                logging.error(f"Error updating progress callback: {str(e)}")
    
    # Make a copy of expenses to avoid modifying the original
    expenses_copy = expenses.copy()
    
    # Sample some expenses for debugging
    sample_size = min(3, len(expenses_copy))
    sample = expenses_copy[:sample_size]
    logging.info(f"Sample of {sample_size} expenses: {sample}")
    
    # Log categories
    category_names = [cat['name'] for cat in categories]
    logging.info(f"Categories: {category_names}")
    
    # Load the prompt template
    prompt_template = load_prompt_template()
    
    # Split expenses into batches for more efficient processing
    batch_size = 5  # Reduced batch size for better performance
    batches = [expenses_copy[i:i+batch_size] for i in range(0, len(expenses_copy), batch_size)]
    total_batches = len(batches)
    
    # Process each batch
    all_results = []
    categorized_count = 0
    
    # Set up progress tracking
    total_expenses = len(expenses_copy)
    
    for i, batch in enumerate(batches):
        progress_pct = (i / total_batches)
        status_msg = f"Categorizing expenses ({i+1}/{total_batches} batches, {progress_pct*100:.1f}% complete)"
        
        if spinner:
            spinner.text = status_msg
        
        update_progress(status_msg, progress_pct)
        logging.info(f"Processing batch {i+1}/{total_batches} ({progress_pct*100:.1f}%)")
        
        try:
            # Check if we can use cached results for all expenses
            all_cached = True
            for expense in batch:
                if force_recategorize:
                    all_cached = False
                    break
                
                # Check if this specific expense has cached results
                batch_key = get_cache_key([expense])
                if not get_cached_results(batch_key):
                    all_cached = False
                    break
            
            if all_cached:
                # If all expenses in this batch have cached results, we can skip processing
                cache_status = f"Using cached results for batch {i+1}/{total_batches}"
                update_progress(cache_status, progress_pct)
                logging.info("Using cached results for all expenses")
                
                for expense in batch:
                    batch_key = get_cache_key([expense])
                    cached = get_cached_results(batch_key)
                    if cached and len(cached) > 0:
                        all_results.extend(cached)
                        categorized_count += 1
                continue
            
            # Process the batch
            batch_results = categorize_expense_batch(batch, categories, prompt_template, force_recategorize)
            
            if batch_results:
                all_results.extend(batch_results)
                categorized_count += len(batch_results)
            else:
                logging.warning(f"No results for batch {i+1}")
                
        except Exception as e:
            logging.error(f"Error processing batch {i+1}: {str(e)}")
    
    # Set final progress
    final_status = f"Categorized {categorized_count}/{total_expenses} expenses"
    if spinner:
        spinner.text = final_status
    
    update_progress(final_status, 1.0)
    
    return all_results

def read_expenses_from_csv(csv_file_path, start_date=None, end_date=None):
    """Read expenses from a CSV file"""
    try:
        if not os.path.exists(csv_file_path):
            logging.error(f"CSV file does not exist: {csv_file_path}")
            return []
        
        # Read the CSV file
        df = pd.read_csv(csv_file_path)
        
        # Check if the CSV has the expected columns
        required_columns = ['Recipient', 'Amount']
        alt_columns = {'Recipient': 'description', 'Amount': 'amount'}
        
        # Log the actual columns for debugging
        logging.info(f"CSV columns: {df.columns.tolist()}")
        
        # Check and rename columns if needed
        columns_to_rename = {}
        for req_col, alt_col in alt_columns.items():
            if req_col not in df.columns and alt_col in df.columns:
                columns_to_rename[alt_col] = req_col
        
        if columns_to_rename:
            df = df.rename(columns=columns_to_rename)
        
        # Ensure required columns exist
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            # Try case-insensitive matching as fallback
            for missing_col in missing_columns.copy():
                for col in df.columns:
                    if col.lower() == missing_col.lower():
                        df = df.rename(columns={col: missing_col})
                        missing_columns.remove(missing_col)
                        break
        
        if missing_columns:
            logging.error(f"CSV missing required columns: {missing_columns}")
            return []
        
        # Convert amount to float
        try:
            df['Amount'] = df['Amount'].apply(lambda x: float(str(x).replace(',', '')) if pd.notnull(x) else 0)
        except Exception as e:
            logging.error(f"Error converting amounts to float: {str(e)}")
        
        # Filter by date if provided
        if start_date and end_date and 'Date' in df.columns:
            try:
                df['Date'] = pd.to_datetime(df['Date'])
                start = pd.to_datetime(start_date)
                end = pd.to_datetime(end_date)
                df = df[(df['Date'] >= start) & (df['Date'] <= end)]
            except Exception as e:
                logging.error(f"Error filtering by date: {str(e)}")
        
        # Convert to list of dictionaries
        expenses = []
        for _, row in df.iterrows():
            expense = {
                'description': row['Recipient'],
                'amount': row['Amount'],
                'date': row['Date'].strftime('%Y-%m-%d') if 'Date' in df.columns and pd.notnull(row['Date']) else None
            }
            expenses.append(expense)
        
        logging.info(f"Read {len(expenses)} expenses from CSV")
        return expenses
    except Exception as e:
        logging.error(f"Error reading expenses from CSV: {str(e)}")
        return []

def generate_final_report(image_path, api_key):
    url = "https://api.deepseek.com/analyze"  # Example endpoint
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "image_path": image_path
    }
    
    response = requests.post(url, headers=headers, json=data)
    
    if response.status_code == 200:
        report = response.json()
        print("Final Report:", report)
    else:
        print("Error generating report:", response.text)

def visualize_expenses(categorized_expenses):
    categories = {}
    for expense in categorized_expenses:
        category = expense[1]  # Assuming the category is at index 1
        amount = expense[2]     # Assuming the amount is at index 2
        if category in categories:
            categories[category] += amount
        else:
            categories[category] = amount

    print("Aggregated Categories:", categories)  # Debugging line

    # Plotting
    plt.figure(figsize=(10, 6))
    plt.bar(categories.keys(), categories.values(), color='skyblue')
    plt.xlabel('Categories')
    plt.ylabel('Total Amount')
    plt.title('Categorized Expenses')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

    # Save the figure to the result_graph_image folder
    save_path = os.path.join(os.path.dirname(__file__), 'result_graph_image', 'categorized_expenses_graph.png')
    plt.savefig(save_path)
    plt.close()  # Close the figure to free up memory

    # Generate the final report after saving the graph
    api_key = "sk-d75907eae31d479d875f9b3578ddb9e5"  # Your actual API key
    generate_final_report(save_path, api_key)

    print("Categorized Expenses for Visualization:", categorized_expenses)  # Debugging line

def send_to_dashboard(categorized_expenses):
    """Save categorized expenses to a file to be read by the Flask app.
    This avoids the 404 error when trying to POST to a non-existent API endpoint.
    """
    try:
        # Save the data to a file in the model directory
        output_file = os.path.join(os.path.dirname(__file__), 'categorized_expenses.json')
        with open(output_file, 'w') as f:
            json.dump({"expenses": categorized_expenses}, f, indent=2)
        logging.info(f"Saved {len(categorized_expenses)} categorized expenses to {output_file} for dashboard display")
        return True
    except Exception as e:
        logging.error(f"Error saving categorized expenses: {str(e)}")
        return False

def main(args=None, transactions=None, progress_callback=None):
    """Main function to categorize expenses and generate visualizations.
    
    Args:
        args: An object with start_date and end_date attributes for filtering expenses.
        transactions: A list of transaction dictionaries that can be directly processed.
        progress_callback: A function to call with progress updates.
    
    Returns:
        A dictionary of categorized expenses.
    """
    try:
        # Define a progress update function that works with or without a callback
        def update_progress(status, percent):
            logging.debug(f"Progress update: {status} - {percent}%")
            if progress_callback:
                progress_callback(status, percent)
            return
        
        # Create a default Args object if none is provided or if it's not the right type
        if args is None or not hasattr(args, 'start_date') or not hasattr(args, 'end_date'):
            class Args:
                def __init__(self):
                    self.start_date = None
                    self.end_date = None
                    self.input_file = None
                    self.output_file = None
                    self.categories_file = "config/categories.yaml"
                    self.prompt_file = "config/prompt.yaml"
                    self.force_recategorize = False
                    self.use_openai = False
            args = Args()
        
        # Load categories
        categories = load_categories()
        
        # Set the model name
        model_name = "llama3"
        
        if transactions is not None:
            # If transactions are directly provided, use them instead of reading from CSV
            update_progress("Processing provided transactions", 85)
            expenses = []
            for txn in transactions:
                try:
                    expense = {
                        'date': txn.get('date', datetime.now().strftime('%Y-%m-%d')),
                        'amount': float(txn.get('amount', 0)),
                        'description': txn.get('recipient', 'Unknown'),
                        'category': '',  # Will be filled in by categorization
                        'transaction_id': txn.get('txn_id', '')
                    }
                    expenses.append(expense)
                except (ValueError, TypeError) as e:
                    logging.warning(f"Failed to convert transaction to expense: {e}")
            
            update_progress("Prepared transactions for categorization", 90)
        else:
            # Default behavior - read from CSV
            csv_file_path = args.input_file or "Gmail_Scrap/cached_transactions.csv"
            update_progress("Reading expenses from CSV", 80)
            expenses = read_expenses_from_csv(csv_file_path, args.start_date, args.end_date)
        
        if not expenses:
            logging.warning("No expenses found to categorize")
            return {}

        # Define a progress callback that maps from categorization progress to overall progress
        def categorization_progress(status, percent):
            # Map from 0-100% in categorization to 40-95% of overall progress
            mapped_percent = 40 + (percent * 0.55)
            update_progress(status, mapped_percent)
            
        # Check if Ollama is running and try to start it if not
        ollama_running = check_ollama_running()
        if not ollama_running:
            update_progress("Starting Ollama service...", 60)
            ollama_started = start_ollama()
            if not ollama_started:
                logging.warning("Could not start Ollama. Will use fallback categorization.")
        
        # Categorize expenses
        update_progress("Categorizing expenses...", 60)
        categorized_expenses = categorize_expenses(
            expenses, 
            categories, 
            force_recategorize=args.force_recategorize,
            progress_callback=categorization_progress
        )
        
        # If output file is specified, save to JSON
        if args.output_file:
            with open(args.output_file, 'w') as f:
                json.dump(categorized_expenses, f, indent=2)
            logging.info(f"Categorized expenses saved to {args.output_file}")
        
        # Attempt to send to dashboard API
        try:
            send_to_dashboard(categorized_expenses)
        except Exception as e:
            logging.warning(f"Failed to send to dashboard API: {e}")
        
        update_progress("Processing complete!", 100)
        return categorized_expenses
        
    except Exception as e:
        logging.error(f"Error in main function: {e}")
        import traceback
        logging.debug(traceback.format_exc())
        update_progress(f"Error: {str(e)}", 80)
        return {}

if __name__ == "__main__":
    main()