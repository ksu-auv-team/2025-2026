from brping import Ping360
import requests
import numpy as np
from modules.SupportAll.DebugHandler import DebugHandler


class Sonar:
    def __init__(self, ip: str = "localhost", port: int = 5000):
        """
        @brief Initializes a Sonar object, setting up the settings for BlueRobotics Ping360 Sonar.
        
        @param self Used to access the Sonar object.
        @param ip Used to set the IP address where the Database is hosted.
        @param port Used to set the Port address where the Database is hosted.

        """
        self.p = Ping360()
        self.url = f'http://{ip}:{port}/sonar'
        self.logData = {}
        self.debug_handler = DebugHandler("SonarSystem", ip, port)

        self.connect_sonar()
        self.initialize_sonar_settings()

    def connect_sonar(self):
        """
        @brief Used to connect to the Sonar using a USB port to facilitate a Serial Connection.
        """
        self.p.connect_serial("/dev/ttyUSB0", 115200)

    def initialize_sonar_settings(self):
        """
        @brief Sets the Settings for the Ping360 Sonar.
        """
        self.p.initialize()
        self.p.set_transmit_frequency(750)
        self.p.set_sample_period(1355)
        self.p.set_number_of_samples(1200)
        self.p.set_gain_setting(0)
        self.p.set_mode(1)
        self.p.set_transmit_duration(40)

    def calculate_sample_distance(self, ping_message, v_sound=1480):
        """
        @brief Calculates the distance that each sample covers.
        @param self Used to access the Sonar class object.
        @param ping_message Used to access data from a ping_message object for calculation.
        @param v_sound Used to represent the velocity of sound underwater.

        @return Returns a value corresponding to the distance in meters that each sample covers.
        """
        return v_sound * ping_message.sample_period * 12.5e-9

    def filter_data_within_range(self, data, lower_limit):
        """
        @brief Crops the gathered data to account for a deadzone surrounding the sonar.
        @param self Used to access the Sonar class object.
        @param data A list that holds the return signal intensity from the sonar.
        @param lower_limit Used to remove data gathered within the deadzone of the sonar.
        """
        return data[lower_limit:]

    def detect_highest_intensity(self, data):
        """
        @brief Find the highest intensity return signal that indicates an object.
        @param self Allows access to the Sonar class object.
        @param data A list that holds intensity data from the Ping360 Sonar.

        @return Returns a value indicating the highest intensity within the data list, and the index of said value.
        """
        highest_value = max(data)
        highest_index = data.index(highest_value)
        return highest_value, highest_index

    def process_scan(self, gradian):
        """
        @brief A run method that handles gathering data to be posted to the database.
        @param self Allows access to the Sonar class object.
        @param gradian Indicates the angle at which the sonar will ping during this function call.

        @return Returns the results from the detect_highest_intensity, the distance that each sample covers, and the cut-off index used to crop the data list.
        """
        d = self.p.transmitAngle(gradian)
        dist_per_sample = self.calculate_sample_distance(d)

        data = np.frombuffer(d.data, dtype=np.uint8)
        lower_limit = int(0.75 // dist_per_sample)+1
        data = self.filter_data_within_range(data, lower_limit)

        return *self.detect_highest_intensity(data), dist_per_sample, lower_limit

    def log_and_send_data(self, gradian, highest_value, highest_index, dist_per_sample, lower_limit):
        """
        @brief Calculates the angle the gradian corresponds to, and then logs the data with the database. The data is also logged in the debug handler.
        @param self Allows access to the Sonar class object.
        @param gradian Indicates the angle at which the sonar is currently pinging.
        @param highest_value Indicates the highest detected signal intensity at a specific gradian.
        @param highest_index Indicates the index the highest_value is at in the data list.
        @param dist_per_sample Indicates the distance in meters that each index in the array covers.
        @param lower_limit The number of indexs that were cropped out of the data list, needed to ensure that calculated distance is correct.
        """
        
        if highest_value >= 127:
            angle = float(0.9 * gradian)
            distance = float((lower_limit+highest_index) * dist_per_sample)
            self.logData = {'angle': angle, 'distance': distance}
            self.debug_handler.set_data("INFO", f"Object Detected at {angle} degrees, {distance} meters.")
            self.send_data()

    def send_data(self):
        """
        @brief Sends data to the database using Flask functions.
        @param self Used to access Sonar class object.
        """
        try:
            response = requests.post(self.url, json=self.logData)
            if response.status_code == 200:
                self.debug_handler.set_data("INFO", "Data successfully sent to the server.")
            else:
                self.debug_handler.set_data("ERROR", f"Failed to send data: {response.text}")
        except requests.exceptions.RequestException as e:
            self.debug_handler.set_data("ERROR", f"Error sending data: {str(e)}")

    def run(self):
        """
        @brief Iterates through each gradian before handling data detection and then recording the results in the database.
        @param self Used to access the Sonar class object.
        """
        try:
            while True:
                for gradian in range(400):
                    highest_value, highest_index, dist_per_sample, lower_limit = self.process_scan(gradian)
                    self.log_and_send_data(gradian, highest_value, highest_index, dist_per_sample, lower_limit)
        except KeyboardInterrupt:
            self.debug_handler.set_data("INFO", "Sonar scan interrupted by user.")
