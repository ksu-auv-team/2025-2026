import requests
import os

def fetch_data(api_url: str) -> dict:
    response = requests.get(api_url)
    if response.status_code == 200:
        return response.json()
    else:
        return {"error": "Failed to fetch data"}


def post_data(api_url: str, data: dict) -> dict:
    response = requests.post(api_url, json=data)
    if response.status_code == 201:
        return response.json()
    else:
        return {"error": "Failed to post data"}


def get_latest_data(api_url: str) -> dict:
    response = requests.get(api_url)
    if response.status_code == 200:
        return response.json()
    else:
        return {"error": "Failed to get latest data"}