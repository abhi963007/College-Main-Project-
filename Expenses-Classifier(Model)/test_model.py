import pandas as pd
from src.classifier import get_label  # Adjusted import path for categorization function

# Load the cleaned CSV file
df = pd.read_csv('test_cleaned_phonepe_transactions.csv')

# Check the structure of the DataFrame
print("Columns in DataFrame:", df.columns)
print("First few rows of the DataFrame:", df.head())

# Assuming the relevant column for categorization is 'Recipient' or 'Message'
# You may need to adjust this based on your actual column names
if 'Recipient' in df.columns:
    df['label'] = df['Recipient'].apply(get_label)
elif 'Message' in df.columns:
    df['label'] = df['Message'].apply(get_label)
else:
    print("No suitable column found for categorization.")

# Save the results to a new CSV file
output_file = 'categorized_phonepe_transactions.csv'
df.to_csv(output_file, index=False)
print(f"Results saved to {output_file}") 