# Agent2
import os

import json
import re

from typing import Optional

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger("Agent1")

from dotenv import load_dotenv
load_dotenv()

from livekit.agents.llm import ChatMessage, ChatRole
from livekit.plugins import silero, openai, elevenlabs
from livekit.agents.llm.chat_context import ChatContext

# Get the absolute path to the directory containing this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------------------------------------------------------
# Agent2 for name/phone extraction
# -------------------------------------------------------------------
class Agent2:
    def __init__(self, llm: openai.LLM, conversation_id: str):
        self.llm = llm
        self._done = False
        self.name: Optional[str] = None
        self.phone: Optional[str] = None
        self.location: Optional[str] = None
        self.service: Optional[str] = None
        self.make: Optional[str] = None
        self.model: Optional[str] = None
        self.color: Optional[str] = None
        self.conversation_id = conversation_id
        self.tx_dir = os.path.join(BASE_DIR, "transcriptions")
        os.makedirs(self.tx_dir, exist_ok=True)
        self.file_written = False
        self.heading = None
        self.summary = None
        self.filename = None
        self.out_path = None

    def needs_vehicle_details(self):
        # List of service types that require vehicle details
        if not self.service:
            return False
        keywords = [
            "tow", "jump", "flat", "tire", "battery", "winch", "stuck", "vehicle", "car", "truck", "van", "unlock", "lockout", "fuel", "out of gas"
        ]
        return any(k in self.service.lower() for k in keywords)

    def has_all_required_info(self):
        # Only require name, phone, location, and service
        required = [self.name, self.phone, self.location, self.service]
        missing = [field for field, value in zip(['name','phone','location','service'], required) if not value]
        if missing:
            logging.getLogger("Agent1").info(f"[Agent2] Missing required fields for transfer: {missing}")
        return all(required)

    def extract_json_from_response(self, resp_content):
        # Remove triple backticks and language tags
        cleaned = re.sub(r"^```[a-zA-Z]*\n?|```$", "", resp_content.strip(), flags=re.MULTILINE)
        cleaned = cleaned.replace('```', '').strip()
        return cleaned

    async def process_history(self, history: list[ChatMessage]):
        convo = "\n".join(
            (m.content[0] if isinstance(m.content, list) else m.content)
            for m in history
        )
        prompt = [
            ChatMessage(
                role="system",
                content=[
                    "Extract caller name, phone number, address or location, service needed, and if mentioned, make, model, and color of the vehicle from the conversation. "
                    "Return JSON: {name: string, phone: string, location: string, service: string, make: string, model: string, color: string}. "
                    "Phone must be 10 digits or null. Location and service must not be empty. If make/model/color are not mentioned, return empty strings."
                ]
            ),
            ChatMessage(role="user", content=[convo[-2000:]])
        ]
        try:
            chat_ctx = ChatContext(items=prompt)
            llm_stream = self.llm.chat(chat_ctx=chat_ctx)
            resp_content = ""
            async for chunk in llm_stream:
                if (
                    hasattr(chunk, "delta") and 
                    hasattr(chunk.delta, "content") and 
                    chunk.delta.content is not None
                ):
                    resp_content += chunk.delta.content
            logger.debug(f"Agent2 LLM extraction response: {resp_content}")
            json_str = self.extract_json_from_response(resp_content)
            # Fix: Ensure valid JSON by replacing single quotes with double quotes if needed
            if json_str.startswith("{") and "'" in json_str and '"' not in json_str:
                json_str = json_str.replace("'", '"')
            # Only attempt to parse if it looks like JSON
            if not (json_str.strip().startswith("{") and json_str.strip().endswith("}")):
                logger.warning(f"Agent2: Skipping non-JSON response: {json_str}")
                return self.name, self.phone, self.location, self.service, self.make, self.model, self.color
            try:
                data = json.loads(json_str)
            except Exception as e:
                logger.warning(f"Agent2: Failed to parse JSON: {json_str} ({e})")
                return self.name, self.phone, self.location, self.service, self.make, self.model, self.color
            phone = re.sub(r"\\D", "", str(data.get("phone") or ""))
            logger.debug(f"Agent2 extracted name: {data.get('name')}, phone: {phone}, location: {data.get('location')}, service: {data.get('service')}, make: {data.get('make')}, model: {data.get('model')}, color: {data.get('color')}")
            if data.get("name") and len(phone) == 10 and data.get("location") and data.get("service"):
                new_name = data["name"].strip()
                safe_name = new_name.replace(" ", "_")
                new_phone = phone
                new_location = data["location"].strip()
                new_service = data["service"].strip()
                new_make = (data.get("make") or "").strip()
                new_model = (data.get("model") or "").strip()
                new_color = (data.get("color") or "").strip()
                new_filename = f"{new_phone}-{safe_name}-{self.conversation_id}.txt"
                new_out_path = os.path.join(self.tx_dir, new_filename)
                if not self._done:
                    self.name = new_name
                    self.phone = new_phone
                    self.location = new_location
                    self.service = new_service
                    self.make = new_make
                    self.model = new_model
                    self.color = new_color
                    self._done = True
                    logger.info(f"Agent2 locked: name={self.name}, phone={self.phone}, location={self.location}, service={self.service}, make={self.make}, model={self.model}, color={self.color}")
                    self.heading = f"Call Transcript for {self.name} ({self.phone})\nSession: {self.conversation_id}\n"
                    self.filename = new_filename
                    self.out_path = new_out_path
                    # Remove the old <uuid>.txt file if it exists
                    old_uuid_file = os.path.join(self.tx_dir, f"{self.conversation_id}.txt")
                    if os.path.exists(old_uuid_file):
                        try:
                            os.remove(old_uuid_file)
                            logger.info(f"Agent2 removed old uuid transcript file: {old_uuid_file}")
                        except Exception as e:
                            logger.warning(f"Agent2 could not remove old uuid transcript file: {old_uuid_file} ({e})")
                else:
                    # If any field changed, rename the file
                    if (self.phone != new_phone or self.name != new_name) and self.out_path and os.path.exists(self.out_path):
                        old_path = self.out_path
                        self.name = new_name
                        self.phone = new_phone
                        self.location = new_location
                        self.service = new_service
                        self.make = new_make
                        self.model = new_model
                        self.color = new_color
                        self.filename = new_filename
                        self.out_path = new_out_path
                        self.heading = f"Call Transcript for {self.name} ({self.phone})\nSession: {self.conversation_id}\n"
                        os.rename(old_path, self.out_path)
                        logger.info(f"Agent2 renamed transcript file to: {self.out_path}")
                    else:
                        self.name = new_name
                        self.phone = new_phone
                        self.location = new_location
                        self.service = new_service
                        self.make = new_make
                        self.model = new_model
                        self.color = new_color
                # Always update summary and transcript
                # Generate summary
                summary_prompt = [
                    ChatMessage(
                        role="system",
                        content=["Summarize the following call in 2-3 sentences."]
                    ),
                    ChatMessage(role="user", content=[convo[-2000:]])
                ]
                summary_ctx = ChatContext(items=summary_prompt)
                summary_stream = self.llm.chat(chat_ctx=summary_ctx)
                summary_content = ""
                async for chunk in summary_stream:
                    if (
                        hasattr(chunk, "delta") and 
                        hasattr(chunk.delta, "content") and 
                        chunk.delta.content is not None
                    ):
                        summary_content += chunk.delta.content
                self.summary = summary_content.strip()
                # Prepend caller info to summary if available
                if self.name and self.phone:
                    self.summary = f"Caller: {self.name}\nPhone: {self.phone}\nLocation: {self.location}\nService: {self.service}\nMake: {self.make}\nModel: {self.model}\nColor: {self.color}\n\n" + self.summary
                # Prepare transcript with both roles
                lines = []
                for m in history:
                    role = getattr(m.role, "name", str(m.role)).lower()
                    text = m.content[0] if isinstance(m.content, list) else m.content
                    if role == "user":
                        lines.append(f"User: {text}")
                    elif role in ("assistant", "ai"):
                        lines.append(f"AI: {text}")
                    else:
                        lines.append(f"{role.capitalize()}: {text}")
                # SAFETY: Only write to .txt files
                if self.out_path and os.path.splitext(self.out_path)[1].lower() == ".txt":
                    extra_info = ""  # <-- Add your extra lines here, e.g. '- Your name is ...\n- Your contact number is ...\n'
                    with open(self.out_path, "w") as f:
                        f.write(self.heading)
                        f.write("\nSummary:\n" + self.summary + "\n\n")
                        f.write(extra_info)
                        f.write("Transcript:\n")
                        f.write("\n".join(lines))
                    logger.info(f"Agent2 updated transcript to: {self.out_path}")
                else:
                    logger.warning(f"Agent2 tried to write transcript to non-txt file: {self.out_path}. Skipping write.")

        except Exception as e:
            logger.error(f"Agent2 error: {e}", exc_info=True)

        return self.name, self.phone, self.location, self.service, self.make, self.model, self.color

# Agent2 does not handle transfer or exit; Agent1/main.py now handle transfer and exit logic.
