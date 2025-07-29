import os
import subprocess
import logging
import re

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("Agent3")

class Agent3:
    def __init__(self, send_script_path=None):
        # Path to sendSipMsg.py
        if send_script_path is None:
            # Default to same directory as this file
            send_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sendSipMsg.py')
        self.send_script_path = send_script_path

    def send_transcription(self, extension, transcription_path, max_length=400):
        """
        Send only the required fields (Caller, Phone, Location, Service, Make, Model, Color) as SIP MESSAGE(s) to the given extension.
        Extract these fields from the transcription file and format them as a concise message.
        """
        if not os.path.exists(transcription_path):
            logger.error(f"Transcription file not found: {transcription_path}")
            return False
        with open(transcription_path, 'r') as f:
            content = f.read()
        # Extract required fields using regex
        fields = ["Caller", "Phone", "Location", "Service", "Make", "Model", "Color"]
        extracted = {}
        for field in fields:
            match = re.search(rf"{field}:\s*(.*)", content)
            if match:
                extracted[field] = match.group(1).strip()
            else:
                extracted[field] = ""
        # Format message
        msg_lines = [f"{field}: {extracted[field]}" for field in fields if extracted[field]]
        message = "\n".join(msg_lines)
        # Split into chunks if too long
        messages = [message[i:i+max_length] for i in range(0, len(message), max_length)]
        for idx, msg in enumerate(messages):
            try:
                logger.info(f"Sending SIP MESSAGE to {extension} (part {idx+1}/{len(messages)})")
                subprocess.run(['python3', self.send_script_path, str(extension), msg], check=True)
            except Exception as e:
                logger.error(f"Failed to send SIP MESSAGE to {extension}: {e}")
                return False
        logger.info(f"Successfully sent transcription to {extension}")
        return True 