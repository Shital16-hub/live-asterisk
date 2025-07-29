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
# import rag  # REMOVE THIS

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
from async_transcript_logger import TranscriptLogger
from rules import evaluate_rules

# Get the absolute path to the directory containing this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------------------------------------------------------
# SessionLogger → logs & dumps transcription with note - REMOVED
# -------------------------------------------------------------------

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
        instructions, initial_history = self._load_initial_context()
        super().__init__(instructions=instructions)
        self.room_name = None
        self.conversation_id = str(uuid.uuid4())
        self.logger: TranscriptLogger | None = None
        self.chat_history: list[ChatMessage] = initial_history
        self.agent2 = Agent2(openai.LLM(model="gpt-4o-mini"), self.conversation_id)
        self.transfer_initiated = False
        self.trunk_id = None
        self.silent_mode = False
        self.is_call_transferred = False  # New flag for post-transfer STT filtering
        self.block_llm = False  # Block LLM after transfer
        agent_name = os.getenv("AI_AGENT_NAME", "nathan").lower()
        self.ai_names = [agent_name, "hey reception"]  # Add wake word
        self._safe_say = None  # Will be set by main.py
        self.call_to_3000_initiated = False  # Track if 3000 was dialed
        self.executive_connected = False    # Track if executive joined
        self._last_service_seen = None  # Track last service for RAG info
        self.last_speech_time = time.time()
        self.waiting_for_field = None  # Track which field the agent is waiting for
        # Pre-create trunk if not already cached
        if Agent1._TRUNK_ID_CACHE is None:
            Agent1._TRUNK_ID_CACHE = self._create_or_get_trunk()
        self.trunk_id = Agent1._TRUNK_ID_CACHE

    async def setup(self):
        """Async setup for things that need await."""
        self.logger = await TranscriptLogger.create()
        self.agent2.set_logger(self.logger)
        logger.info("TranscriptLogger initialized and set in Agent2.")

    def _load_initial_context(self) -> tuple[str | None, list[ChatMessage]]:
        prompt_path = os.path.join(BASE_DIR, "prompts", "system.json")
        try:
            with open(prompt_path) as f:
                data = json.load(f)
        except (IOError, json.JSONDecodeError):
            logger.error(f"Failed to load or parse system prompt from {prompt_path}")
            return "You are a helpful assistant.", []

        initial_history = []
        instructions = None
        agent_name = os.getenv("AI_AGENT_NAME", "nathan").capitalize()

        for item in data:
            role_str = item.get("role")
            raw_content = item.get("content")

            if not role_str or not raw_content:
                continue
            
            # Map role string to ChatRole enum
            role = "system"
            if role_str.lower() == "user":
                role = "user"
            elif role_str.lower() == "assistant":
                role = "assistant"
            
            # Handle both string and list-of-string format for content
            if isinstance(raw_content, list):
                content = "\n".join(raw_content)
            else:
                content = str(raw_content)

            # Dynamically replace the hardcoded name in the prompt
            content = content.replace("Nathan Wills", agent_name)
            content = content.replace("Nathan", agent_name)

            initial_history.append(ChatMessage(role=role, content=[content]))

            # The first system message is used for the Agent's instructions
            if role == "system" and instructions is None:
                instructions = content

        return instructions, initial_history

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

    async def get_routing_action_from_llm(self, collected_data: dict) -> str:
        """
        Uses the LLM to decide on the routing action based on rules.json.
        """
        rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")
        try:
            with open(rules_path) as f:
                rules_config = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load or parse rules.json: {e}")
            return "transfer"  # Default to transfer on error

        routing_rules = [rule for rule in rules_config.get("rules", []) if rule.get("stage") == "routing"]
        default_action = rules_config.get("default_action", "transfer")

        conversation_summary = collected_data.get("summary", "")
        service_needed = collected_data.get("service", "")
        full_transcript = collected_data.get("full_transcript", "")

        prompt_content = (
            "You are an intelligent call routing agent. Your task is to decide the next action for a call based on a set of rules and the conversation context. "
            "The possible actions are 'transfer' or 'end_call'.\n\n"
            "Here are the routing rules:\n"
            f"{json.dumps(routing_rules, indent=2)}\n\n"
            f"The default action if no rule matches is: '{default_action}'\n\n"
            "Here is the information from the call:\n"
            f"- Service Needed: {service_needed}\n"
            f"- Conversation Summary: {conversation_summary}\n"
            f"- Full Transcript (last part): {full_transcript[-500:]}\n\n"
            "Based on the rules and the call information, what is the correct action? "
            "Respond with only the action as a single word: 'transfer' or 'end_call'."
        )

        prompt = [
            ChatMessage(role="system", content=[prompt_content]),
        ]

        try:
            llm = self.agent2.llm
            chat_ctx = ChatContext(items=prompt)
            resp_content = ""
            async for chunk in llm.chat(chat_ctx=chat_ctx):
                if hasattr(chunk.delta, "content") and chunk.delta.content:
                    resp_content += chunk.delta.content
            
            action = resp_content.strip().lower().replace("'", "").replace('"', '')
            logger.info(f"[Agent1] LLM routing decision: '{action}'")

            if action in ["transfer", "end_call"]:
                return action
            else:
                logger.warning(f"[Agent1] LLM returned an invalid routing action: '{action}'. Defaulting to transfer.")
                return "transfer"

        except Exception as e:
            logger.error(f"[Agent1] LLM routing decision failed: {e}")
            return "transfer" # Fail safe

    async def should_call(self) -> bool:
        logger.info(f"[Agent1] should_call: transfer_initiated={self.transfer_initiated}, has_all_required_info={self.agent2.has_all_required_info()}, ready_for_transfer={getattr(self, 'ready_for_transfer', False)}")
        if self.transfer_initiated:
            return False
            
        if not self.agent2.has_all_required_info():
            # Reset the timer if info is missing
            if hasattr(self, '_all_info_ready_time'):
                del self._all_info_ready_time
            return False

        # All required info is present. Now let the LLM decide the action.
        collected_data = self.agent2.get_collected_data()
        action = await self.get_routing_action_from_llm(collected_data)

        if action == "end_call":
            logger.info("[Agent1] Rule action: end_call. Terminating session.")
            if not self.transfer_initiated:
                self.transfer_initiated = True # Prevent re-entry
                # Log to MongoDB: transfered: false, call_action: end_call
                if self.logger:
                    log_data = self.agent2.get_collected_data()
                    log_data["transfered"] = False
                    log_data["call_action"] = "end_call"
                    await self.logger.upsert_log(self.conversation_id, log_data)
                await self.safe_say("We have your number and will be in contact shortly. Thank you for calling. Goodbye.")
                await asyncio.sleep(5)
                if self.ctx and hasattr(self.ctx.room, 'disconnect'):
                    await self.ctx.room.disconnect()
                else:
                    sys.exit(0) # Fallback
            return False # Signal not to transfer.

        if action == "transfer":
            logger.info("[Agent1] Rule action: transfer. Proceeding with transfer logic.")
            import time
            now = time.time()
            if not hasattr(self, '_all_info_ready_time'):
                self._all_info_ready_time = now
            if getattr(self, 'ready_for_transfer', False):
                # Log to MongoDB: transfered: true, call_action: transfer
                if self.logger:
                    log_data = self.agent2.get_collected_data()
                    log_data["transfered"] = True
                    log_data["call_action"] = "transfer"
                    await self.logger.upsert_log(self.conversation_id, log_data)
                return True
            if now - self._all_info_ready_time > 10:
                logger.info("[Agent1] Fallback: allowing transfer after 10s with all info present.")
                # Log to MongoDB: transfered: true, call_action: transfer
                if self.logger:
                    log_data = self.agent2.get_collected_data()
                    log_data["transfered"] = True
                    log_data["call_action"] = "transfer"
                    await self.logger.upsert_log(self.conversation_id, log_data)
                return True
            return False
        
        if action == "spam":
            if not self.transfer_initiated:
                self.transfer_initiated = True
                # Log to MongoDB: transfered: false, call_action: spam
                if self.logger:
                    log_data = self.agent2.get_collected_data()
                    log_data["transfered"] = False
                    log_data["call_action"] = "spam"
                    await self.logger.upsert_log(self.conversation_id, log_data)
                await self.safe_say("Thank you for calling. Goodbye.")
                await asyncio.sleep(1)
                if self.ctx and hasattr(self.ctx.room, 'disconnect'):
                    await self.ctx.room.disconnect()
                else:
                    sys.exit(0)
            return True

        if action == "no_action":
            logger.info("[Agent1] Rule action: no_action. Continuing to prompt for missing info.")
            return False  # Do nothing, keep prompting

        # Fallback for any other unknown action
        logger.warning(f"[Agent1] Unknown action from 'routing' rules: '{action}'. Defaulting to not transfer.")
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
            success = agentCaller.join_sip_participant(trunk_id, "4000", self.room_name)
            if success:
                self.call_to_3000_initiated = True
                logger.info("[Agent1] SIP 3000 call initiated.")
        else:
            logger.info("[Agent1] SIP 3000 call already initiated, skipping repeat dial.")

        if self.call_to_3000_initiated:
            logger.info(f"[Agent1] Successfully initiated transfer to SIP 3000 in room {self.room_name}")
            # Wait for the human agent to answer (room_member:<room_name> key in Redis)
            import redis
            import random
            r = redis.Redis(host='15.204.51.230', port=6379, db=0, password='2123tt')
            key = f'room_member:{self.room_name}'
            max_retries = 15 # ~30 seconds
            interval = 2  # seconds
            member_value = None

            hold_messages = [
                "We are connecting you now, please hold.",
                "Trying to reach an executive for you.",
                "Thank you for your patience, we're connecting your call.",
                "Please stay on the line, we're finding someone for you.",
            ]
            last_hold_message_index = -1

            logger.info(f"[Agent1] Checking for room_member key: {key} (up to {max_retries} times)")
            for attempt in range(max_retries):
                val = r.get(key)
                logger.info(f"[Agent1] Attempt {attempt+1}: {key} = {val}")
                if val:
                    member_value = val.decode()
                    logger.info(f"[Agent1] Found room_member: {member_value} for room {self.room_name}")
                    break

                # Speak a hold message every 4 attempts (8 seconds)
                if attempt > 0 and attempt % 4 == 0:
                    next_message_index = random.randint(0, len(hold_messages) - 1)
                    if next_message_index == last_hold_message_index:
                        next_message_index = (next_message_index + 1) % len(hold_messages)
                    last_hold_message_index = next_message_index
                    await self.safe_say(hold_messages[next_message_index])

                await asyncio.sleep(interval)
            
            if member_value:
                # Parse ip, port, extension
                try:
                    ip, port, extension = member_value.split(":")
                except Exception as e:
                    logger.error(f"[Agent1] Failed to parse room_member value '{member_value}': {e}")
                    sys.exit(1)
                # Log the SIP info for the transfer
                if self.logger:
                    sip_log_data = {
                        "sip_info": {
                            "ip": ip,
                            "port": port,
                            "extension": extension
                        },
                        "transfered": True,
                        "call_action": "transfer"
                    }
                    await self.logger.upsert_log(self.conversation_id, sip_log_data)
                    logger.info(f"[Agent1] Logged SIP transfer info for conversation {self.conversation_id}")

                # Send SIP MESSAGE to the agent with the collected info
                sip_message_content = self.agent2.sip_message
                if sip_message_content:
                    a3 = agent3.Agent3()
                    logger.info(f"[Agent1] About to send SIP MESSAGE to {extension} at {ip}:{port} for room {self.room_name}")
                    await asyncio.sleep(3)  # Wait to ensure agent is ready
                    max_send_retries = 3
                    for send_attempt in range(max_send_retries):
                        success = a3.send_transcription_to_room_member(self.room_name, sip_message_content, redis_host="15.204.51.230", redis_port=6379, redis_password="2123tt", override_ip=ip, override_port=port, override_extension=extension)
                        if success:
                            logger.info(f"[Agent1] Sent transcription to room member {extension} at {ip}:{port} for room {self.room_name} via Agent3 (attempt {send_attempt+1})")
                            break
                        logger.warning(f"[Agent1] Retry {send_attempt+1} failed to send SIP MESSAGE. Retrying...")
                        await asyncio.sleep(2)
                    else:
                        logger.error(f"[Agent1] Failed to send SIP MESSAGE after {max_send_retries} attempts.")
                else:
                    logger.warning(f"[Agent1] No transcript content found in agent2 to send to agent for room {self.room_name}")
                logger.info("[Agent1] Exiting after successful transfer and executive connection.")
                sys.exit(0)
                return
            else:
                logger.error(f"[Agent1] room_member key not found after {max_retries} attempts. Exiting anyway.")
                await self.safe_say("Could not confirm executive connection, exiting.")
                await asyncio.sleep(4)
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
            r = redis.Redis(host='15.204.51.230', port=6379, db=0, password='2123tt')
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
        await self.agent2.process_history(self.chat_history)
        if not self.agent2.has_all_required_info():
            logger.info("[Agent1] Not all required info present after confirmation. Blocking transfer.")
            await self.safe_say("Sorry, I still need some information before I can transfer your call.")
            return
        await self.safe_say("Thank you for confirming. I'll now connect you to our team to complete your request. Please hold on a moment.", mark_ready_for_transfer=True)
        await asyncio.sleep(4)

    async def check_for_emergency_and_transfer(self):
        """
        Checks for emergencies using rules and LLM, and triggers an immediate transfer if detected.
        Returns True if an emergency was handled, False otherwise.
        """
        if self.transfer_initiated:
            return False

        collected_data = self.agent2.get_collected_data()
        if not collected_data.get("full_transcript"):
            return False

        action = evaluate_rules(collected_data, stage="emergency_check")

        if action == "transfer":
            logger.info("[Agent1] Potential emergency detected by keyword. Verifying with LLM.")
            
            last_message = self.chat_history[-1].content[0] if self.chat_history and isinstance(self.chat_history[-1].content, list) else (self.chat_history[-1].content if self.chat_history else "")

            prompt = [
                ChatMessage(
                    role="system",
                    content=[(
                        "You are an emergency detection system for a towing company. "
                        "Analyze the user's message. An emergency is a situation requiring immediate human intervention for safety. "
                        "Examples: car accidents, injuries, fire, being in a dangerous location. "
                        "A simple breakdown is NOT an emergency. "
                        "Respond with 'EMERGENCY' for a critical emergency, or 'ROUTINE' otherwise. Only use these exact words."
                    )]
                ),
                ChatMessage(role="user", content=[last_message])
            ]

            try:
                llm = self.agent2.llm
                chat_ctx = ChatContext(items=prompt)
                resp_content = ""
                async for chunk in llm.chat(chat_ctx=chat_ctx):
                    if hasattr(chunk.delta, "content") and chunk.delta.content:
                        resp_content += chunk.delta.content
                
                logger.info(f"[Agent1] LLM Emergency Check Response: '{resp_content.strip()}'")
                if "emergency" in resp_content.strip().lower():
                    logger.warning("[Agent1] LLM confirmed EMERGENCY. Transferring immediately.")
                    await self.safe_say("I've detected an emergency. Connecting you to an operator right away.")
                    await self.transfer()
                    return True
                else:
                    logger.info("[Agent1] LLM classified as ROUTINE. Proceeding normally.")
            except Exception as e:
                logger.error(f"[Agent1] LLM emergency check failed: {e}. Transferring as a precaution.")
                await self.safe_say("Connecting you to an operator for assistance.")
                await self.transfer()
                return True
        
        return False

    async def is_spam_with_llm(self, history: list[ChatMessage]) -> bool:
        """
        Uses the LLM to determine if the conversation is spam.
        """
        logger.info("[Agent1] Verifying potential spam with LLM.")
        convo = "\n".join(
            (m.content[0] if isinstance(m.content, list) else m.content)
            for m in history
        )
        
        prompt = [
            ChatMessage(
                role="system",
                content=[(
                    "You are a spam detection expert. Analyze the following conversation transcript. "
                    "The user is calling a towing company. "
                    "If the user is trying to sell something (like marketing, business loans) or it's clearly an unwanted call, it is spam. "
                    "If the user is asking for towing services, asking about payment methods, or has a legitimate-sounding query, it is NOT spam. "
                    "Respond with 'SPAM' if it is spam, and 'NOT SPAM' otherwise. Only respond with those exact words."
                )]
            ),
            ChatMessage(role="user", content=[convo[-1000:]]) # Use last 1000 chars
        ]

        try:
            # We need an LLM instance to call chat. We can reuse the one from agent2.
            # This assumes agent2's llm is accessible. A better design might pass the llm to agent1.
            llm = self.agent2.llm
            chat_ctx = ChatContext(items=prompt)
            llm_stream = llm.chat(chat_ctx=chat_ctx)
            
            resp_content = ""
            async for chunk in llm_stream:
                if (
                    hasattr(chunk, "delta") and
                    hasattr(chunk.delta, "content") and
                    chunk.delta.content is not None
                ):
                    resp_content += chunk.delta.content
            
            logger.info(f"[Agent1] LLM Spam Check Response: '{resp_content.strip()}'")
            return "spam" in resp_content.strip().lower()
        except Exception as e:
            logger.error(f"[Agent1] LLM spam check failed: {e}")
            return False # Fail safe: assume not spam if LLM fails

    async def hangup_if_spam(self):
        """
        Checks for spam and hangs up the call if detected.
        Returns True if the call was spam and hung up, False otherwise.
        """
        collected_data = self.agent2.get_collected_data()
        # Don't check for spam on an empty transcript
        if not collected_data.get("full_transcript"):
            return False

        action = evaluate_rules(collected_data, stage="spam_check")

        if action == "spam":
            if not self.transfer_initiated:
                self.transfer_initiated = True
                # Log to MongoDB: transfered: false, call_action: spam
                if self.logger:
                    log_data = self.agent2.get_collected_data()
                    log_data["transfered"] = False
                    log_data["call_action"] = "spam"
                    await self.logger.upsert_log(self.conversation_id, log_data)
                await self.safe_say("Thank you for calling. Goodbye.")
                await asyncio.sleep(1)
                if self.ctx and hasattr(self.ctx.room, 'disconnect'):
                    await self.ctx.room.disconnect()
                else:
                    sys.exit(0)
            return True

        return False

