import requests
import os
from dotenv import load_dotenv


def get_label(desc):
    try:
        load_dotenv()
        api_key = os.environ['DEEPSEEK_API_KEY']
        base_url = "https://api.deepseek.com/v1/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": f"Expense description: {desc}"}
        ]

        data = {
            "model": "deepseek-chat",
            "messages": messages,
            "stream": False
        }

        print("Calling DeepSeek API with description:", desc)
        response = requests.post(base_url, headers=headers, json=data)
        response.raise_for_status()  # Raise an error for bad responses
        completion = response.json()
        print("API response:", completion)

        return completion['choices'][0]['message']['content']
    except Exception as e:
        print(f"An error occurred: {e}")
        return " "