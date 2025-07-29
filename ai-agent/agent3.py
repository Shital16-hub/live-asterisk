import os
import subprocess
import logging
import re
import redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("Agent3")

class Agent3:
    def __init__(self, send_script_path=None):
        # Path to sendSipMsg.py
        if send_script_path is None:
            # Default to same directory as this file
            send_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sendSipMsg.py')
        self.send_script_path = send_script_path

    def send_transcription(self, extension, transcription_path, max_length=400, sip_server="65.19.173.80", sip_port=5080):
        """
        Send only the required fields (Caller, Phone, Location, Service, Make, Model, Color) as SIP MESSAGE(s) to the given extension.
        Extract these fields from the transcription file and format them as a concise message.
        By default, sends to SIP server 65.19.173.80:5080 unless overridden.
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
        message = "; ".join(msg_lines)  # Use '; ' as separator for single-argument passing
        # Split into chunks if too long
        messages = [message[i:i+max_length] for i in range(0, len(message), max_length)]
        for idx, msg in enumerate(messages):
            try:
                logger.info(f"Sending SIP MESSAGE to {extension} (part {idx+1}/{len(messages)})")
                cmd = ['python3', self.send_script_path, str(extension), msg]
                if sip_server and sip_port:
                    cmd.extend([str(sip_server), str(sip_port)])
                subprocess.run(cmd, check=True)
            except Exception as e:
                logger.error(f"Failed to send SIP MESSAGE to {extension}: {e}")
                return False
        logger.info(f"Successfully sent transcription to {extension}")
        return True

    def send_transcription_to_room_member(self, room_name, message, redis_host="15.204.51.230", redis_port=6379, redis_password="2123tt", override_ip=None, override_port=None, override_extension=None):
        """
        Look up the SIP endpoint for the given room in Redis and send the transcript to that endpoint.
        The Redis value should be in the format ip:port:extension.
        If override_ip, override_port, and override_extension are provided, use them instead of querying Redis.
        """
        logger.info(f"Looking up room member for {room_name} in Redis...")
        ip = port = extension = None
        if override_ip and override_port and override_extension:
            ip = override_ip
            port = override_port
            extension = override_extension
            logger.info(f"Using override SIP endpoint: {ip}:{port}:{extension}")
        else:
            r = redis.Redis(host=redis_host, port=redis_port, db=0, password=redis_password)
            key = f"room_member:{room_name}"
            value = r.get(key)
            if not value:
                logger.error(f"No room member found in Redis for key {key}")
                return False
            try:
                ip, port, extension = value.decode().split(":")
            except Exception as e:
                logger.error(f"Failed to parse room_member value '{value.decode()}': {e}")
                return False
        
        if not message:
            logger.error("No message content provided to send.")
            return False

        # Call sendSipMsg.py
        cmd = ["python3", "ai-agent/sendSipMsg.py", extension, message, ip, port]
        logger.info(f"Sending SIP MESSAGE to {extension} at {ip}:{port}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                logger.info(f"Successfully sent SIP MESSAGE to {extension} at {ip}:{port}")
                return True
            else:
                logger.error(f"Failed to send SIP MESSAGE: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Exception while sending SIP MESSAGE: {e}")
            return False 