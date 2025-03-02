from flask import Flask, request, render_template, send_file
import os
import pandas as pd
from data_handling import get_creditcard_entry, get_bank_acc_entry, get_revolut_entry
from classifier import get_label

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Handle file upload
        uploaded_files = request.files.getlist('files')
        dfs = []
        for file in uploaded_files:
            if file.filename.endswith('.xlsx'):
                df = pd.read_excel(file)
                dfs.append(df)
        if dfs:
            # Concatenate all dataframes
            conc_df = pd.concat(dfs, axis=0, ignore_index=True)
            print("Uploaded files:", uploaded_files)
            print("Concatenated DataFrame:", conc_df.head())
            print("Columns in concatenated DataFrame:", conc_df.columns)
            print("First few rows of the DataFrame:", conc_df.head())
            conc_df['label'] = conc_df['desc'].apply(get_label)
            output_file = 'files/output.xlsx'
            conc_df.to_excel(output_file, index=False)
            if os.path.exists(output_file):
                print("Output file created successfully:", output_file)
            else:
                print("Failed to create output file.")
            return send_file(output_file, as_attachment=True)
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True) 