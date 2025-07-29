# Agent2
import os

import json
import re

from typing import Optional, TYPE_CHECKING

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

if TYPE_CHECKING:
    from async_transcript_logger import TranscriptLogger

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
        self.year: Optional[str] = None
        self.conversation_id = conversation_id
        # self.tx_dir = os.path.join(BASE_DIR, "transcriptions")
        # os.makedirs(self.tx_dir, exist_ok=True)
        # self.file_written = False
        self.heading = None
        self.summary = None
        # self.filename = None
        # self.out_path = None
        self.sip_message: Optional[str] = None
        self.logger: Optional["TranscriptLogger"] = None
        self.full_transcript: Optional[str] = None

    def set_logger(self, logger: "TranscriptLogger"):
        self.logger = logger

    def needs_vehicle_details(self):
        # List of service types that require vehicle details
        if not self.service:
            return False
        keywords = [
            "tow", "jump", "flat", "tire", "battery", "winch", "stuck", "vehicle", "car", "truck", "van", "unlock", "lockout", "fuel", "out of gas"
        ]
        return any(k in self.service.lower() for k in keywords)

    def get_collected_data(self) -> dict:
        """Returns all collected data as a dictionary."""
        return {
            "name": self.name,
            "phone": self.phone,
            "location": self.location,
            "service": self.service,
            "make": self.make,
            "model": self.model,
            "color": self.color,
            "year": self.year,
            "summary": self.summary,
            "full_transcript": self.full_transcript
        }

    def has_all_required_info(self):
        # Require name, phone, location, service, year, and at least one of make/model
        required = [self.name, self.phone, self.location, self.service, self.year]
        has_make_or_model = bool(self.make) or bool(self.model)
        missing = [field for field, value in zip(['name','phone','location','service','year'], required) if not value]
        if not has_make_or_model:
            missing.append('make/model')
        if missing:
            logging.getLogger("Agent1").info(f"[Agent2] Missing required fields for transfer: {missing}")
        return all(required) and has_make_or_model

    def extract_json_from_response(self, resp_content):
        # Remove triple backticks and language tags
        cleaned = re.sub(r"^```[a-zA-Z]*\n?|```$", "", resp_content.strip(), flags=re.MULTILINE)
        cleaned = cleaned.replace('```', '').strip()
        return cleaned

    async def process_history(self, history: list[ChatMessage]):
        # Use the full conversation history for extraction
        convo = "\n".join(
            (m.content[0] if isinstance(m.content, list) else m.content)
            for m in history
        )
        agent_name = os.getenv("AI_AGENT_NAME", "nathan")
        prompt = [
            ChatMessage(
                role="system",
                content=[
                    (f"Extract the caller's information from the conversation: their name, phone number, address or location, and the specific service they need. "
                     f"Also extract vehicle make, model, color, and year if mentioned. The AI agent introduces itself as {agent_name.capitalize()}; do not extract this as the caller's name. "
                     "Return JSON: {name: string, phone: string, location: string, service: string, make: string, model: string, color: string, year: string}. "
                     "The 'name' field must be the caller's name. Phone must be 10 digits or empty string. Location and service must not be empty. "
                     "For the 'service' field, extract the core service type (e.g., 'lockout', 'jump', 'tire', 'fuel'), not full phrases like 'lockout service' or 'jump start service'. "
                     "If any field is missing or not mentioned, use the value from earlier in the conversation if available; otherwise, return an empty string. Never return null."
                     )
                ]
            ),
            ChatMessage(role="user", content=[convo[-32000:]])
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

            def clean_value(value):
                if value is None or (isinstance(value, str) and value.strip().lower() == 'null'):
                    return ""
                return str(value).strip()

            extracted_fields = [
                clean_value(data.get("name")),
                clean_value(data.get("phone")),
                clean_value(data.get("service")),
                clean_value(data.get("location")),
                clean_value(data.get("make")),
                clean_value(data.get("model")),
                clean_value(data.get("year")),
                clean_value(data.get("color")),
            ]
            # Enforce order: name, phone, service, location, make, model, year
            # Only update if not already set, unless user provided out of order
            field_names = ["name", "phone", "service", "location", "make", "model", "year", "color"]
            for idx, field in enumerate(field_names):
                val = extracted_fields[idx]
                if val and not getattr(self, field):
                    setattr(self, field, val)
                    # Update transcript and summary before logging
                    lines = []
                    for m in history:
                        role = getattr(m.role, "name", str(m.role)).lower()
                        text = m.content[0] if isinstance(m.content, list) else m.content
                        if role == "user":
                            clean_text = re.split(r"\s*RAG SEARCH RESULTS:", text, flags=re.IGNORECASE)[0].strip()
                            if clean_text:
                                lines.append(f"User: {clean_text}")
                        elif role in ("assistant", "ai"):
                            clean_text = text.strip()
                            if clean_text:
                                lines.append(f"AI: {clean_text}")
                    self.full_transcript = "\n".join(lines)
                    # Generate summary (short, even if not all info present)
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
                    # Determine if basic_info is present
                    service_list = [
                        "lockout", "jump", "jump start", "tire", "fuel", "battery", "key", "ignition", "roadside",
                        "tow", "towing", "accident", "recovery", "winch", "heavy duty", "commercial", "big rig", "semi", "bus", "truck", "trailer", "container", "flatbed", "motorhome", "rv"
                    ]
                    basic_info = bool(self.name and self.phone and self.service and any(s in (self.service or '').lower() for s in service_list))
                    # Log to MongoDB after each field update, with latest transcript/summary and basic_info
                    if self.logger:
                        log_data = {
                            "conversation_id": self.conversation_id,
                            "ai_agent_name": agent_name,
                            "caller_name": self.name or '',
                            "caller_phone": self.phone or '',
                            "location": self.location or '',
                            "service": self.service or '',
                            "vehicle_make": self.make or '',
                            "vehicle_model": self.model or '',
                            "vehicle_color": self.color or '',
                            "vehicle_year": self.year or '',
                            "summary": self.summary,
                            "full_transcript": self.full_transcript,
                            "basic_info": basic_info,
                            "call_action": "no_action"
                        }
                        await self.logger.upsert_log(self.conversation_id, log_data)

            # Only generate summary and transcript ONCE, when all required info is present
            if self.name and self.phone and self.location and self.service and self.year and (self.make or self.model) and not self._done:
                self._done = True
                logger.info(f"Agent2 locked: name={self.name}, phone={self.phone}, location={self.location}, service={self.service}, make={self.make}, model={self.model}, color={self.color}, year={self.year}")

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

                # Prepare transcript with both roles, cleaning up noise
                lines = []
                for m in history:
                    role = getattr(m.role, "name", str(m.role)).lower()
                    text = m.content[0] if isinstance(m.content, list) else m.content
                    if role == "user":
                        clean_text = re.split(r"\s*RAG SEARCH RESULTS:", text, flags=re.IGNORECASE)[0].strip()
                        if clean_text:
                            lines.append(f"User: {clean_text}")
                    elif role in ("assistant", "ai"):
                        clean_text = text.strip()
                        if clean_text:
                            lines.append(f"AI: {clean_text}")
                full_transcript = "\n".join(lines)
                self.full_transcript = full_transcript

                # Prepare data for MongoDB and SIP message
                sip_lines = [
                    f"Caller: {self.name or ''}",
                    f"Phone: {self.phone or ''}",
                    f"Location: {self.location or ''}",
                    f"Service: {self.service or ''}",
                    f"Make: {self.make or ''}",
                    f"Model: {self.model or ''}",
                    f"Color: {self.color or ''}",
                    f"Year: {self.year or ''}",
                    "",
                    "Summary:",
                    self.summary,
                    "",
                    "Transcript:",
                    full_transcript
                ]
                self.sip_message = "\n".join(sip_lines)

                log_data = {
                    "conversation_id": self.conversation_id,
                    "ai_agent_name": agent_name,
                    "caller_name": self.name or '',
                    "caller_phone": self.phone or '',
                    "location": self.location or '',
                    "service": self.service or '',
                    "vehicle_make": self.make or '',
                    "vehicle_model": self.model or '',
                    "vehicle_color": self.color or '',
                    "vehicle_year": self.year or '',
                    "summary": self.summary,
                    "full_transcript": full_transcript
                }
                if self.logger:
                    await self.logger.upsert_log(self.conversation_id, log_data)
                    logger.info(f"Agent2 upserted log for conversation: {self.conversation_id}")
                else:
                    logger.warning("Agent2 logger not set, skipping database log.")

        except Exception as e:
            logger.error(f"Agent2 error: {e}", exc_info=True)
        return self.name, self.phone, self.location, self.service, self.make, self.model, self.color

    def missing_name_or_phone(self):
        missing = []
        if not self.name:
            missing.append('name')
        if not self.phone:
            missing.append('phone')
        return missing

# Agent2 does not handle transfer or exit; Agent1/main.py now handle transfer and exit logic.

# NOTE: VAD sensitivity/threshold is not currently configurable via the LiveKit Silero plugin. If needed, patch the plugin or request this feature upstream.
