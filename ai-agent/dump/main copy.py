#!/usr/bin/env python3
# main.py
import os
import sys
import asyncio
import logging
import tempfile
import time
import fcntl
import socket
import redis
import json
from datetime import datetime
import uuid
import contextlib
import psutil

from dotenv import load_dotenv

from livekit.agents import (
    AgentSession,
    JobContext,
    cli,
    WorkerOptions,
    ConversationItemAddedEvent,
)
from livekit.plugins import silero, openai

from agent1 import Agent1  # your core agent logic
from LLMw import openaiLLM

# ─── Logging setup ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger("enhanced-telephony-agent")
for noisy in ("openai", "httpx", "urllib3", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

# ─── Voice Coordinator (prevents double voice) ─────────────────────
class VoiceCoordinator:
    """Coordinates which process is allowed to speak for a given room"""
    
    def __init__(self):
        try:
            self.redis = redis.Redis(host='15.204.51.230', port=6379, db=0, password='2123tt')
            self.redis.ping()  # Test connection
            self.use_redis = True
            logger.info("Using Redis for voice coordination")
        except (redis.ConnectionError, redis.RedisError):
            self.use_redis = False
            logger.warning("Redis not available, falling back to file-based locks")
        self.process_id = f"{os.getpid()}-{socket.gethostname()}-{int(time.time())}-{uuid.uuid4()}"
        logger.info(f"[VoiceCoordinator] This process_id: {self.process_id}")

    @contextlib.contextmanager
    def global_speaker_lock(self, room_name, timeout=10):
        """Context manager for a Redis-based global lock per room. Only one process can hold it at a time."""
        lock_key = f"voice_global_lock:{room_name}"
        lock_val = self.process_id
        have_lock = False
        try:
            if self.use_redis:
                # Try to acquire the lock
                have_lock = self.redis.set(lock_key, lock_val, nx=True, ex=timeout)
                if have_lock:
                    logger.info(f"[VoiceCoordinator] {self.process_id} acquired global speaker lock for {room_name}")
                else:
                    logger.warning(f"[VoiceCoordinator] {self.process_id} could NOT acquire global speaker lock for {room_name}")
                yield have_lock
                # Only the lock holder should release
                if have_lock and self.redis.get(lock_key) == lock_val.encode():
                    self.redis.delete(lock_key)
                    logger.info(f"[VoiceCoordinator] {self.process_id} released global speaker lock for {room_name}")
            else:
                # Fallback: always allow
                yield True
        except Exception as e:
            logger.error(f"[VoiceCoordinator] Error in global_speaker_lock: {e}")
            yield False

    def register_as_speaker(self, room_name, ttl=60):
        """Register this process as the designated speaker for the room"""
        if self.use_redis:
            # First check if anyone else is registered
            current_speaker = self.redis.get(f"voice_leader:{room_name}")
            if current_speaker is not None and current_speaker.decode() != self.process_id:
                logger.warning(f"Room {room_name} already has a speaker: {current_speaker.decode()} (this process: {self.process_id})")
                return False
                
            # Try to register as speaker with TTL
            success = self.redis.set(f"voice_leader:{room_name}", self.process_id, ex=ttl, nx=True)
            if success:
                logger.info(f"Process {self.process_id} registered as speaker for room {room_name}")
                return True
            else:
                logger.warning(f"Failed to register as speaker for room {room_name} (process_id: {self.process_id})")
                return False
        else:
            # Fall back to file-based lock
            lock_path = os.path.join(tempfile.gettempdir(), f"voice_lock_{room_name.replace('-','_')}")
            try:
                with open(lock_path, 'w') as f:
                    try:
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        f.write(self.process_id)
                        f.flush()
                        logger.info(f"[VoiceCoordinator] File lock acquired for {room_name} by {self.process_id}")
                        return True
                    except (IOError, BlockingIOError):
                        logger.warning(f"[VoiceCoordinator] File lock busy for {room_name}, process_id: {self.process_id}")
                        return False
            except Exception as e:
                logger.error(f"Lock error: {e}")
                return False
    
    def is_designated_speaker(self, room_name):
        """Check if this process is the designated speaker for the room, and clean up if the holder is dead."""
        if self.use_redis:
            try:
                current = self.redis.get(f"voice_leader:{room_name}")
                if not current:
                    return False
                # Verify process exists
                pid_part = current.decode().split("-")[0]
                try:
                    pid_int = int(pid_part)
                    if not psutil.pid_exists(pid_int):
                        self.redis.delete(f"voice_leader:{room_name}")
                        logger.info(f"[VoiceCoordinator] Cleaned up dead speaker lock for {room_name} (pid {pid_int})")
                        return False
                except Exception:
                    pass
                is_speaker = current.decode() == self.process_id
                logger.info(f"[VoiceCoordinator] is_designated_speaker({room_name}): {is_speaker} (current: {current}, this: {self.process_id})")
                return is_speaker
            except Exception as e:
                logger.error(f"[VoiceCoordinator] Redis error in is_designated_speaker: {e}")
                return False
        else:
            # Fall back to checking file
            lock_path = os.path.join(tempfile.gettempdir(), f"voice_lock_{room_name.replace('-','_')}")
            try:
                with open(lock_path, 'r') as f:
                    file_pid = f.read().strip()
                    is_speaker = file_pid == self.process_id
                    logger.info(f"[VoiceCoordinator] is_designated_speaker({room_name}): {is_speaker} (file: {file_pid}, this: {self.process_id})")
                    return is_speaker
            except Exception as e:
                logger.error(f"[VoiceCoordinator] File error in is_designated_speaker: {e}")
                return False
                
    def refresh_speaker_status(self, room_name, ttl=60):
        """Refresh this process's status as the speaker (extends TTL)"""
        if self.use_redis and self.is_designated_speaker(room_name):
            self.redis.expire(f"voice_leader:{room_name}", ttl)
            return True
        return False

    def unregister_as_speaker(self, room_name):
        """Unregister as speaker for the room"""
        if self.use_redis and self.is_designated_speaker(room_name):
            self.redis.delete(f"voice_leader:{room_name}")
            logger.info(f"Unregistered as speaker for room {room_name}")
            return True
        return False

# Create global coordinator
voice_coordinator = VoiceCoordinator()

# ─── Entrypoint ────────────────────────────────────────────────────
async def entrypoint(ctx: JobContext):
    room_name = ctx.room.name
    logger.info(f"Entrypoint start for room {room_name} (PID {os.getpid()})")
    # Immediate check with Redis
    r = redis.Redis(host='15.204.51.230', port=6379, db=0, password='2123tt')
    agent_key = f"active_agent:{room_name}"
    current_agent = r.get(agent_key)
    logger.info(f"[Agent Entrypoint] Redis slot before set: {current_agent}")
    if current_agent:
        logger.info(f"Another agent {current_agent} active for {room_name}, exiting")
        return
    # Claim the slot (longer expiry)
    r.set(agent_key, str(os.getpid()), ex=120)
    logger.info(f"[Agent Entrypoint] Claimed Redis slot for {room_name} with PID {os.getpid()}")
    # Periodically renew the slot
    async def renew_agent_slot():
        while True:
            await asyncio.sleep(30)
            r.set(agent_key, str(os.getpid()), ex=120)
            logger.info(f"[Agent Slot] Renewed Redis slot for {room_name} with PID {os.getpid()}")
    asyncio.create_task(renew_agent_slot())
    try:
        await ctx.connect()

        # Try to register as speaker for this room
        is_speaker = voice_coordinator.register_as_speaker(room_name)
        logger.info(f"Process {os.getpid()} {'IS' if is_speaker else 'IS NOT'} the designated speaker for room {room_name}")

        # Start speaker refresh task if we're the speaker
        if is_speaker:
            async def refresh_speaker_status():
                while True:
                    await asyncio.sleep(15)  # Refresh every 15 seconds
                    voice_coordinator.refresh_speaker_status(room_name, ttl=60)
            refresh_task = asyncio.create_task(refresh_speaker_status())

        # Prevent duplicate handler/task registration
        if getattr(ctx, '_handlers_registered', False):
            logger.warning(f"Handlers already registered for {room_name}, skipping re-registration.")
            return
        ctx._handlers_registered = True

        # instantiate your agent core
        agent = Agent1()
        agent.room_name = room_name  # Stash the dynamic room name on the agent
        agent.set_session_context(ctx)  # Set session context for transfer/disconnect

        # ─── Safe TTS helper with speaker check ────────────────────────
        async def safe_say(text: str):
            # Strict silence: if agent is in silent_mode, only allow if 'nathan' is in the last user message
            if getattr(agent, 'silent_mode', False):
                # Only allow if last user message contains 'nathan'
                last_user = next((item for item in reversed(agent.chat_history) if getattr(item.role, 'name', str(item.role)).lower() == 'user'), None)
                if last_user:
                    user_text = last_user.content[0] if isinstance(last_user.content, list) else last_user.content
                    if 'nathan' not in user_text.lower():
                        logger.info("AI is in strict silent mode. Not speaking unless addressed by 'nathan'.")
                        return
            with voice_coordinator.global_speaker_lock(room_name, timeout=10) as have_lock:
                if not have_lock:
                    logger.warning(f"[VoiceCoordinator] {voice_coordinator.process_id} could not get global lock for {room_name}, skipping speech: {text}")
                    return
                if not voice_coordinator.is_designated_speaker(room_name):
                    logger.warning(f"Process {os.getpid()} skipping speech - not the designated speaker for room {room_name} (process_id: {voice_coordinator.process_id})")
                    return
                try:
                    logger.info(f"Process {os.getpid()} speaking as designated speaker for room {room_name} (process_id: {voice_coordinator.process_id}) - Saying: {text}")
                    await session.say(text)
                except Exception as e:
                    logger.error(f"TTS error: {e} (no fallback available)")

        # Set the safe_say function on the agent
        agent.set_safe_say(safe_say)

        # Add periodic agent presence validation (with startup delay)
        async def validate_presence():
            await asyncio.sleep(2)
            while True:
                await asyncio.sleep(2)
                current_pid = r.get(agent_key)
                logger.info(f"[Agent Presence] Redis slot: {current_pid}, my PID: {os.getpid()}")
                if current_pid is None:
                    # Reclaim the slot if missing
                    logger.info(f"[Agent Presence] Redis slot missing, reclaiming for {room_name}")
                    r.set(agent_key, str(os.getpid()), ex=120)
                elif current_pid.decode() != str(os.getpid()):
                    logger.info(f"[Agent Presence] Another agent took over for {room_name}, exiting")
                    os._exit(0)
        asyncio.create_task(validate_presence())

        # load required plugins
        try:
            vad = silero.VAD.load()
            stt = openai.STT(model="gpt-4o-transcribe")
            # stt = openai.STT(model="gpt-4o-mini-transcribe")
            # llm = openaiLLM(model="gpt-4o-mini")
            llm = openai.LLM(model="gpt-4o-mini")
            # llm = openai.LLM(model="gpt-4.1")

            tts = openai.TTS(
                model="gpt-4o-mini-tts",
                voice="ash",
                instructions=(
                    "Open with a normal, professional greeting and introduce yourself as a service assistant. "
                    "Speak in a friendly, empathetic tone with clear enunciation and moderate pacing—about 150 words per minute. "
                    "Use natural intonation and occasional, thoughtful pauses between sentences. "
                    "Emphasize key information by slightly raising pitch or pausing before and after important points. "
                    "Maintain consistency and a conversational flow throughout the call."
                )
            )
            # ["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse"]
        except Exception as e:
            logger.error(f"Plugin initialization failed: {e}")
            await ctx.room.disconnect()
            return

        session = AgentSession(vad=vad, stt=stt, llm=llm, tts=tts)

        # ─── 1) Logging and history capture ─────────────────────────────
        last_logged = {'role': None, 'text': None}
        def on_item(evt: ConversationItemAddedEvent):
            item = evt.item
            role = getattr(item.role, "name", str(item.role))
            content = item.content
            text = content[0] if isinstance(content, list) else content
            # Debounce: only log if not identical to last
            if role == last_logged['role'] and text == last_logged['text']:
                return
            last_logged['role'] = role
            last_logged['text'] = text
            if isinstance(text, str):
                agent.logger.log_interaction(role, text)
                agent.logger.log_raw(role, text)
            agent.chat_history.append(item)

            # Only respond if allowed (not in silent mode, or addressed by name)
            if role.lower() == "user":
                # After transfer, only process user speech if it contains 'hey reception'
                if getattr(agent, 'is_call_transferred', False):
                    if 'hey reception' not in text.lower():
                        logger.info("STT: User speech ignored after transfer (no wake word).")
                        return  # Do not add to chat history or process further
                if not agent.should_respond(text):
                    logger.info("AI is in silent mode and was not addressed by name. Skipping response.")
                    return
            # Block all AI/system-initiated speech after transfer
            if getattr(agent, 'silent_mode', False) and role.lower() in ("assistant", "ai"):
                # Only allow if last user message contains 'nathan'
                last_user = next((item for item in reversed(agent.chat_history) if getattr(item.role, 'name', str(item.role)).lower() == 'user'), None)
                if last_user:
                    user_text = last_user.content[0] if isinstance(last_user.content, list) else last_user.content
                    if 'nathan' not in user_text.lower():
                        logger.info("AI is in strict silent mode. Not speaking unless addressed by 'nathan'. (AI/system message)")
                        return

            # --- NEW: Trigger final confirmation after user confirms recap ---
            if role.lower() == "user" and text.strip().lower() in ["yes", "correct", "that's right", "yep", "yeah"]:
                # Look back for recap/confirmation from AI
                for prev in reversed(agent.chat_history[:-1]):
                    prev_role = getattr(prev.role, "name", str(prev.role)).lower()
                    prev_text = prev.content[0] if isinstance(prev.content, list) else prev.content
                    if prev_role in ("assistant", "ai") and "is everything accurate" in prev_text.lower():
                        if not getattr(agent, 'ready_for_transfer', False):
                            asyncio.create_task(agent.speak_final_confirmation())
                        break

            # --- NEW: Trigger final confirmation if agent says the transfer message directly ---
            if role.lower() in ("assistant", "ai"):
                norm_text = text.lower().replace("'", "").replace("'", "").replace(",", "").replace(".", "").replace("!", "").replace("-", " ")
                if "now connect you to our team to complete your request please hold on a moment" in norm_text:
                    if not getattr(agent, 'ready_for_transfer', False):
                        asyncio.create_task(agent.speak_final_confirmation())

        session.on("conversation_item_added", on_item)

        # ─── 3) Save transcript on disconnect ───────────────────────────
        session.on("session_disconnected", lambda e: agent.logger.dump_transcription_with_note())

        # ─── 4) Start background extraction loop ────────────────────────
        if not hasattr(ctx, '_periodic_task'):
            async def periodic_check():
                last_speech_time = time.time()
                while True:
                    try:
                        await asyncio.sleep(5)
                        # Only process LLM if not blocked, or if last user message contains 'hey reception'
                        if getattr(agent, 'block_llm', False):
                            last_user = next((item for item in reversed(agent.chat_history) if getattr(item.role, 'name', str(item.role)).lower() == 'user'), None)
                            if not (last_user and 'hey reception' in (last_user.content[0] if isinstance(last_user.content, list) else last_user.content).lower()):
                                logger.info("Periodic check: Blocked LLM after transfer (block_llm, no wake word).")
                                continue  # Skip LLM call
                        await agent.agent2.process_history(agent.chat_history)
                        await agent.maybe_speak_service_info(agent.chat_history)
                        
                        # Check for silence and greet if needed
                        current_time = time.time()
                        if current_time - last_speech_time > 10 and not agent.silent_mode:
                            await safe_say("Hello? Are you still there?")
                            last_speech_time = current_time

                        # Check if transfer is needed
                        if not agent.transfer_initiated:
                            try:
                                await agent.trigger_transfer_if_ready()
                                if agent.transfer_initiated:
                                    return  # Stop the periodic check after transfer
                            except Exception as e:
                                logger.error(f"Transfer sequence failed: {e}")
                                if agent.transfer_initiated:
                                    return
                    except Exception as e:
                        logger.error(f"Periodic check error: {e}")
                        if agent.transfer_initiated:
                            return
            ctx._periodic_task = asyncio.create_task(periodic_check())

        # ─── 5) Run the session ─────────────────────────────────────────
        try:
            logger.info("Starting session...")
            await session.start(agent=agent, room=ctx.room)
            logger.info("Session started, sending initial greeting...")
            # Send initial greeting after session is started
            await safe_say("Hello! Thank you for calling. How may I assist you today?")
            logger.info("Initial greeting sent")
        except Exception as e:
            logger.error(f"Session error: {e}")
            if agent.transfer_initiated:
                # Only delete slot on intentional shutdown
                logger.info(f"[Agent Entrypoint] Releasing Redis slot for {room_name} (transfer)")
                r.delete(agent_key)
                os._exit(0)  # Exit if we were transferring
            raise
        finally:
            agent.logger.dump_transcription_with_note()
            if is_speaker:
                voice_coordinator.unregister_as_speaker(room_name)
            if agent.transfer_initiated:
                # Only delete slot on intentional shutdown
                logger.info(f"[Agent Entrypoint] Releasing Redis slot for {room_name} (transfer/disconnect)")
                r.delete(agent_key)
                os._exit(0)  # Ensure exit after transfer
    except Exception as e:
        logger.error(f"[Agent Entrypoint] Exception: {e}")
        # Only delete slot on intentional shutdown
        logger.info(f"[Agent Entrypoint] Releasing Redis slot for {room_name} (exception)")
        r.delete(agent_key)
        raise


# ─── CLI bootstrap ────────────────────────────────────────────────
if __name__ == "__main__":
    load_dotenv()
    if os.getenv("LIVEKIT_ROOM"):
        sys.argv = [sys.argv[0], "connect", "--room", os.getenv("LIVEKIT_ROOM")]

    opts = WorkerOptions(
        ws_url=os.getenv("LIVEKIT_URL"),
        api_key=os.getenv("LIVEKIT_API_KEY"),
        api_secret=os.getenv("LIVEKIT_API_SECRET"),
        entrypoint_fnc=entrypoint,
        agent_name="enhanced-telephony-agent",
    )

    try:
        cli.run_app(opts)
    except KeyboardInterrupt:
        logger.info("Shutting down")
    except Exception:
        logger.exception("Unhandled crash")
    finally:
        logger.info("Service stopped")