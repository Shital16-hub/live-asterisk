# Agent1
import os
import uuid
import json
import asyncio
# import telnetlib
import requests
import jwt
import datetime
import time
import random
import string
import signal
import sys
import redis

from datetime import datetime


import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger("Agent1")

from dotenv import load_dotenv
load_dotenv()

from livekit.agents import (
    Agent,
)
from livekit.agents.llm import ChatMessage, ChatRole
from livekit.plugins import silero, openai, elevenlabs
from livekit.agents.llm.chat_context import ChatContext

from agent2 import Agent2
import agentCaller
import agent3

# Get the absolute path to the directory containing this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------------------------------------------------------
# SessionLogger → logs & dumps transcription with note
# -------------------------------------------------------------------
class SessionLogger:
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.log_dir = os.path.join(BASE_DIR, "logs")
        self.tx_dir  = os.path.join(BASE_DIR, "transcriptions")

        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.tx_dir,  exist_ok=True)

        # Startup test
        with open(os.path.join(self.log_dir, "_startup_test.log"), "a") as f:
            f.write(f"Startup @ {datetime.now().isoformat()}\n")

        # Main log header
        self.log_file = os.path.join(self.log_dir, f"{conversation_id}.log")
        with open(self.log_file, "w") as f:
            f.write(
                f"=== Conversation {conversation_id} started @ "
                f"{datetime.now().isoformat()} ===\n"
            )
        # Raw log file
        self.raw_file = os.path.join(self.log_dir, f"{conversation_id}_raw.txt")
        # In-memory buffers
        self._log_buffer = []
        self._raw_buffer = []
        self._last_flushed_user_lines = set()
        self._last_transcript = None
        self._flush_lock = asyncio.Lock()  # For async safety

    def log_interaction(self, role: str, text: str):
        logger.debug(f"Buffering {role!r}: {text!r}")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._log_buffer.append(f"[{ts}] {role}: {text}\n")

    def log_raw(self, role: str, text: str):
        self._raw_buffer.append(f"{role}: {text}\n")

    async def flush(self):
        async with self._flush_lock:
            if self._log_buffer:
                try:
                    with open(self.log_file, "a") as f:
                        f.writelines(self._log_buffer)
                    self._log_buffer.clear()
                except Exception as e:
                    logger.error(f"Failed to flush log: {e}")
            if self._raw_buffer:
                try:
                    with open(self.raw_file, "a") as f:
                        f.writelines(self._raw_buffer)
                    self._raw_buffer.clear()
                except Exception as e:
                    logger.error(f"Failed to flush raw log: {e}")

    async def periodic_flush(self, interval=5):
        while True:
            await asyncio.sleep(interval)
            await self.flush()

    async def dump_transcription_with_note(self):
        await self.flush()  # Ensure all logs are written
        note = (
            "An optional Agent2 loop extracts name & phone from the accumulating chat_history.\n\n"
        )
        try:
            with open(self.log_file, "r") as f:
                user_lines = [l for l in f if "] USER:" in l]
            # Only write if new user lines are present
            user_lines_set = set(user_lines)
            if user_lines_set == self._last_flushed_user_lines:
                logger.info(f"No new user lines for transcript; skipping write.")
                return
            self._last_flushed_user_lines = user_lines_set
            out_path = os.path.join(self.tx_dir, f"{self.conversation_id}.txt")
            transcript = note + ''.join(user_lines)
            if transcript == self._last_transcript:
                logger.info(f"Transcript unchanged; skipping write.")
                return
            self._last_transcript = transcript
            with open(out_path, "w") as tf:
                tf.write(transcript)
            logger.info(f"✔ Transcription + note written to: {out_path}")
        except Exception as e:
            logger.error(f"Failed to write transcription file: {e}")


# -------------------------------------------------------------------
# Main Agent (instructions & context preservation)
# -------------------------------------------------------------------
class Agent1(Agent):
    LIVEKIT_API_KEY    = os.getenv("LIVEKIT_API_KEY")
    LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
    LIVEKIT_REST_URL   = os.getenv("LIVEKIT_REST_URL", "http://15.204.51.230:7880")
    SIP_EXTENSION      = "3000"
    SIP_TRUNK_ADDRESS  = os.getenv("SIP_TRUNK_ADDRESS",  "15.204.51.230:5070")
    SIP_TRUNK_USER     = os.getenv("SIP_TRUNK_USER",     "livekitgw")
    SIP_TRUNK_PASS     = os.getenv("SIP_TRUNK_PASS",     "passgw")
    _TRUNK_ID_CACHE    = None  # Class-level cache for trunk ID

    def __init__(self):
        super().__init__(instructions=self._load_instructions())
        self.room_name = None
        self.conversation_id = str(uuid.uuid4())
        self.logger = SessionLogger(self.conversation_id)
        self.chat_history: list[ChatMessage] = []
        self.agent2 = Agent2(openai.LLM(model="gpt-4o-mini"), self.conversation_id)
        self._flush_task = asyncio.create_task(self.logger.periodic_flush())
        self.transfer_initiated = False
        self.trunk_id = None
        self.silent_mode = False
        self.is_call_transferred = False  # New flag for post-transfer STT filtering
        self.block_llm = False  # Block LLM after transfer
        self.ai_names = ["hey reception"]  # Add wake word
        self._safe_say = None  # Will be set by main.py
        self.call_to_3000_initiated = False  # Track if 3000 was dialed
        self.executive_connected = False    # Track if executive joined
        # Pre-create trunk if not already cached
        if Agent1._TRUNK_ID_CACHE is None:
            Agent1._TRUNK_ID_CACHE = self._create_or_get_trunk()
        self.trunk_id = Agent1._TRUNK_ID_CACHE

    def _load_instructions(self) -> str:
        prompt_path = os.path.join(BASE_DIR, "prompts", "system.json")
        with open(prompt_path) as f:
            return json.load(f)[0]["content"]

    def _generate_jwt(self) -> str:
        payload = {
            "iss": self.LIVEKIT_API_KEY,
            "sub": "sip-service",
            "exp": int(time.time()) + 3600,
            "sip": {
                "admin": True,
                "trunk_management": True,
                "participant_management": True
            }
        }
        return jwt.encode(payload, self.LIVEKIT_API_SECRET, algorithm="HS256")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._generate_jwt()}",
            "Content-Type": "application/json",
        }

    def _create_or_get_trunk(self):
        # List existing trunks and reuse if possible
        url_list = f"{self.LIVEKIT_REST_URL}/twirp/livekit.SIP/ListSIPOutboundTrunk"
        r = requests.post(url_list, headers=self._headers(), json={})
        if r.status_code == 200:
            trunks = r.json().get("sip_trunks", [])
            for trunk in trunks:
                if trunk.get("address") == self.SIP_TRUNK_ADDRESS:
                    logger.info(f"[Agent1] Found existing trunk: {trunk['sip_trunk_id']}")
                    return trunk["sip_trunk_id"]
        else:
            logger.error(f"[Agent1] Failed to list trunks: {r.status_code} {r.text}")
        # Create trunk if not found
        name = "AsteriskTrunk-" + "".join(random.choices(string.ascii_lowercase+string.digits, k=6))
        body = {
            "trunk": {
                "name":         name,
                "address":      self.SIP_TRUNK_ADDRESS,
                "auth_username":self.SIP_TRUNK_USER,
                "auth_password":self.SIP_TRUNK_PASS,
                "numbers":      [ self.SIP_EXTENSION ],
            }
        }
        url_create = f"{self.LIVEKIT_REST_URL}/twirp/livekit.SIP/CreateSIPOutboundTrunk"
        r = requests.post(url_create, headers=self._headers(), json=body)
        logger.info(f"[Agent1] CreateSIPOutboundTrunk response: {r.status_code} {r.text}")
        r.raise_for_status()
        return r.json()["sip_trunk_id"]

    def _maybe_create_trunk(self):
        # Use cached trunk ID if available
        if self.trunk_id:
            return
        if Agent1._TRUNK_ID_CACHE is None:
            Agent1._TRUNK_ID_CACHE = self._create_or_get_trunk()
        self.trunk_id = Agent1._TRUNK_ID_CACHE

    def join_sip_participant(self, extension, identity=None):
        """
        Join a SIP extension (e.g., 1001, 3000) to the current LiveKit room.
        """
        self._maybe_create_trunk()
        payload = {
            "sip_trunk_id": self.trunk_id,
            "sip_call_to": extension,
            "room_name": self.room_name,
            "participant_identity": identity or f"sip-{extension}",
        }
        url = f"{self.LIVEKIT_REST_URL}/twirp/livekit.SIP/CreateSIPParticipant"
        try:
            r = requests.post(url, headers=self._headers(), json=payload)
            logger.info(f"[Agent1] SIP participant {extension} join response: {r.status_code} {r.text}")
            r.raise_for_status()
        except Exception as e:
            logger.error(f"[Agent1] Failed to join SIP participant {extension}: {e}")
            raise

    def set_session_context(self, ctx):
        """Store the session context for later use (e.g., to disconnect)."""
        self.ctx = ctx

    def set_safe_say(self, safe_say_func):
        """Set the safe_say function from main.py"""
        self._safe_say = safe_say_func

    async def safe_say(self, text: str, mark_ready_for_transfer=False):
        """Wrapper for the safe_say function from main.py. Optionally mark ready for transfer after this speech."""
        if self._safe_say is None:
            logger.error("[Agent1] safe_say function not set")
            return
        await self._safe_say(text)
        if mark_ready_for_transfer:
            self.ready_for_transfer = True

    async def should_call(self) -> bool:
        logger.info(f"[Agent1] should_call: transfer_initiated={self.transfer_initiated}, has_all_required_info={self.agent2.has_all_required_info()}, ready_for_transfer={getattr(self, 'ready_for_transfer', False)}")
        if self.transfer_initiated:
            return False
        if not self.agent2.has_all_required_info():
            # Reset the timer if info is missing
            if hasattr(self, '_all_info_ready_time'):
                del self._all_info_ready_time
            return False
        # If all info just became available, start a timer
        import time
        now = time.time()
        if not hasattr(self, '_all_info_ready_time'):
            self._all_info_ready_time = now
        # Allow transfer if ready_for_transfer is True, or if 10 seconds have passed since all info was ready
        if getattr(self, 'ready_for_transfer', False):
            return True
        if now - self._all_info_ready_time > 10:
            logger.info("[Agent1] Fallback: allowing transfer after 10s with all info present.")
            return True
        return False

    async def trigger_transfer_if_ready(self):
        logger.info(f"[Agent1] trigger_transfer_if_ready called")
        if await self.should_call():
            logger.info(f"[Agent1] trigger_transfer_if_ready: should_call is True, calling transfer()")
            await self.transfer()
        else:
            logger.info(f"[Agent1] trigger_transfer_if_ready: should_call is False, not calling transfer()")

    async def transfer(self):
        logger.info(f"[Agent1] transfer called. transfer_initiated={self.transfer_initiated}")
        if self.transfer_initiated:
            return
        self.transfer_initiated = True
        self.silent_mode = True  # Go silent as soon as transfer is triggered
        self.is_call_transferred = True  # Set flag for STT filtering
        self.block_llm = True  # Block LLM after transfer
        logger.info(f"[Agent1] Transferring: joining SIP 3000 to room {self.room_name} via agentCaller.")

        # Only announce and dial once
        if not self.call_to_3000_initiated:
            await self.safe_say("Connecting to our executive.")
            await asyncio.sleep(2)
            trunk_id = agentCaller.get_or_create_trunk()
            logger.info(f"[Agent1] Using trunk_id: {trunk_id}")
            success = agentCaller.join_sip_participant(trunk_id, "3000", self.room_name)
            if success:
                self.call_to_3000_initiated = True
                logger.info("[Agent1] SIP 3000 call initiated.")
        else:
            logger.info("[Agent1] SIP 3000 call already initiated, skipping repeat dial.")

        if self.call_to_3000_initiated:
            logger.info(f"[Agent1] Successfully initiated transfer to SIP 3000 in room {self.room_name}")
            # Wait for the human agent to answer (room_answered:<room_name> key in Redis)
            import redis
            import time
            r = redis.Redis(host='localhost', port=6379, db=0)
            key = f'room_answered:{self.room_name}'
            timeout = 20  # seconds
            interval = 0.5  # seconds
            waited = 0
            agent_exten = None
            logger.info(f"[Agent1] Waiting for human agent to answer (key: {key})")
            while waited < timeout:
                val = r.get(key)
                logger.info(f"[Agent1] Polling for {key}: {val}")
                if val:
                    agent_exten = val.decode()
                    logger.info(f"[Agent1] Human agent {agent_exten} answered for room {self.room_name}")
                    break
                time.sleep(interval)
                waited += interval
            if agent_exten:
                # Send SIP MESSAGE to the agent with the collected info
                tx_path = self.agent2.out_path if hasattr(self.agent2, 'out_path') else None
                if tx_path and os.path.exists(tx_path):
                    import agent3
                    a3 = agent3.Agent3()
                    logger.info(f"[Agent1] About to send SIP MESSAGE to {agent_exten} with transcript: {tx_path}")
                    a3.send_transcription(agent_exten, tx_path)
                    logger.info(f"[Agent1] Sent transcription to agent {agent_exten} via Agent3")
                else:
                    logger.warning(f"[Agent1] No transcription file found to send to agent {agent_exten}")
                logger.info("[Agent1] Exiting after successful transfer and executive connection.")
                sys.exit(0)
                return
            else:
                logger.error(f"[Agent1] No human agent answered within timeout period. Exiting anyway.")
                await self.safe_say("Could not confirm executive connection, exiting.")
                await asyncio.sleep(2)
                sys.exit(0)
                return
        else:
            logger.error(f"[Agent1] Failed to join SIP 3000 to room {self.room_name}")
            await self.safe_say("I apologize, but I'm unable to connect you to our executive at this time. Please try calling back in a few minutes.")
            return

    def set_room_name(self, room: str):
        self.room_name = room
        logger.info(f"[Agent1] Room name set to {room}")
        try:
            r = redis.Redis(host='localhost', port=6379, db=0)
            r.set('current_room_name', room)
            logger.info(f"[Agent1] Wrote room name {room} to Redis under 'current_room_name'")
        except Exception as e:
            logger.error(f"[Agent1] Failed to write room name to Redis: {e}")

    def get_current_channel(self):
        # TODO: Implement logic to get the current channel name for the call
        # This is a placeholder. You may need to pass the channel from main.py/session context.
        # For now, try to get from environment or return None
        return os.environ.get("ASTERISK_CHANNEL")

    def should_respond(self, text: str) -> bool:
        """
        In silent_mode, only respond if 'nathan' is in the user text (case-insensitive).
        Otherwise, respond as normal.
        """
        if not self.silent_mode:
            return True
        # In silent mode, only respond if explicitly called by name 'nathan'
        lowered = text.lower()
        return any(name in lowered for name in self.ai_names)

    async def speak_final_confirmation(self):
        # This should be called after all info is confirmed and before transfer
        # Force a final extraction/update of all fields
        await self.agent2.process_history(self.chat_history)
        if not self.agent2.has_all_required_info():
            logger.info("[Agent1] Not all required info present after confirmation. Blocking transfer.")
            await self.safe_say("Sorry, I still need some information before I can transfer your call.")
            return
        await self.safe_say("Thank you for confirming. I'll now connect you to our team to complete your request. Please hold on a moment.", mark_ready_for_transfer=True)
        await asyncio.sleep(2)

