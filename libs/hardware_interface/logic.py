import requests
import json


def sendDataToServer(data: dict, url: str) -> None:
    """
    data: dict - Contains the sensor data acquired from the hardware.
    url: str - The server URL where the data will be sent.

    Splits the data by 

    """
    try:
        response = requests.post(url, json=data)
        response.raise_for_status()  # Raise an error for bad responses
    except requests.RequestException as e:
        raise requests.RequestException(f"HTTP request failed: {e}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Error decoding JSON from response: {e}")

def getDataFromServer(url) -> dict:
    """
    Retrieve data from a server via HTTP GET request.

    Args:
        url (str): The server URL from which the data will be retrieved.

    Returns:
        dict: Server response parsed as JSON.

    Raises:
        requests.RequestException: If the request fails.
        json.JSONDecodeError: If the response is not valid JSON.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses
        return response.json()
    except requests.RequestException as e:
        raise requests.RequestException(f"HTTP request failed: {e}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Error decoding JSON from response: {e}")
    
def splitData(data : dict) -> tuple[dict, dict, dict]:
    """
    @brief Splits the input data into separate dictionaries for motors, torpedoes, and arm.

    @param data: The input data dictionary to split.
    @return: A tuple containing three dictionaries: motors, torpedoes, and arm.
    """
    motors = {}
    torps = {}
    arm = {}
    for key in data.keys():
        if key.startswith("M"):
            motors[key] = data[key]
        elif key in ["S1", "S2"]:
            torps[key] = data[key]
        elif key == "S3":
            arm[key] = data[key]

    return motors, torps, arm