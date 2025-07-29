#!/usr/bin/env python3
# manager.py
import os
import asyncio
import subprocess
import time
from datetime import datetime
from dotenv import load_dotenv
import signal
import sys
import psutil
import redis
import uuid

# 1) Server SDK imports
from livekit import api
from livekit.api.room_service import ListRoomsRequest

# 2) Load configuration
load_dotenv()  # expects LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_ROOM_PREFIX, MAIN_SCRIPT

LIVEKIT_URL    = os.getenv("LIVEKIT_URL_HTTP", "http://localhost:7880")
API_KEY        = os.getenv("LIVEKIT_API_KEY")
API_SECRET     = os.getenv("LIVEKIT_API_SECRET")
ROOM_PREFIX    = os.getenv("LIVEKIT_ROOM_PREFIX", "room1-")
POLL_INTERVAL  = float(os.getenv("POLL_INTERVAL", "4.0"))
GRACE_PERIOD   = float(os.getenv("GRACE_PERIOD", "8"))
LAUNCH_LOCK_TIMEOUT = int(os.getenv("LAUNCH_LOCK_TIMEOUT", "15"))
LOG_FILE       = os.getenv("MANAGER_LOG_FILE", "manager.log")

# Get the absolute path to main.py based on this script's location
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.getenv("MAIN_SCRIPT", os.path.join(BASE_DIR, "main.py"))

# Track running subprocesses and their removal time
launched       = {}
removal_times  = {}

ZOMBIE_CLEANUP_INTERVAL = 5  # seconds
last_zombie_cleanup     = 0.0

# Add Redis connection for launch locking
def get_redis():
    try:
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
        return r
    except Exception as e:
        print(f"[manager] Redis unavailable for launch lock: {e}")
        return None

redis_client = get_redis()

def log(msg: str):
    line = f"{datetime.now().isoformat()} {msg}"
    print(line)

def cleanup_zombies():
    # Only kill main.py processes that were started WITHOUT a LIVEKIT_ROOM env var
    try:
        for proc in psutil.process_iter(['pid', 'cmdline']):
            if proc.pid == os.getpid():
                continue
            cmd = proc.info.get('cmdline') or []
            if "main.py" not in " ".join(cmd):
                continue
            # if the process has LIVEKIT_ROOM set, assume it's one of ours and skip it
            try:
                child_env = proc.environ()
                if child_env.get("LIVEKIT_ROOM"):
                    continue
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                # if we can't read env, play it safe and skip
                continue
            log(f"[manager] Cleaning up truly orphaned main.py process: PID {proc.pid}")
            proc.terminate()
    except Exception as e:
        log(f"[manager] Zombie cleanup error: {e}")

def kill_main_py_for_room(room: str):
    """Kill any main.py processes tied to a given LIVEKIT_ROOM."""
    for _ in range(10):  # 10 attempts with 0.5s intervals (5s total)
        found = False
        for proc in psutil.process_iter(['pid', 'cmdline', 'environ']):
            try:
                cmd = " ".join(proc.info.get('cmdline') or [])
                if "main.py" in cmd:
                    env = proc.info.get('environ') or {}
                    if env.get("LIVEKIT_ROOM") == room or room in cmd:
                        found = True
                        log(f"Terminating PID {proc.pid} for {room}")
                        proc.terminate()
                        try:
                            proc.wait(timeout=1)
                        except Exception:
                            pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not found:
            break
        time.sleep(0.5)

async def list_rooms() -> list[str]:
    """Fetch current rooms via LiveKit Server RPC."""
    lkapi = api.LiveKitAPI(LIVEKIT_URL, API_KEY, API_SECRET)
    try:
        resp = await lkapi.room.list_rooms(ListRoomsRequest())
        return [r.name for r in resp.rooms]
    finally:
        await lkapi.aclose()

async def renew_lock_periodically(redis, key, val):
    while True:
        await asyncio.sleep(LAUNCH_LOCK_TIMEOUT/3)
        redis.set(key, val, ex=LAUNCH_LOCK_TIMEOUT)
        log(f"[manager] Renewed launch lock for {key}")

async def manager():
    global last_zombie_cleanup

    while True:
        try:
            now = time.time()
            log("[manager] Polling")

            # periodic zombie cleanup
            if now - last_zombie_cleanup > ZOMBIE_CLEANUP_INTERVAL:
                cleanup_zombies()
                last_zombie_cleanup = now

            # list and filter rooms
            try:
                rooms = await list_rooms()
                active = [r for r in rooms if r.startswith(ROOM_PREFIX)]
            except Exception as e:
                log(f"[manager] Error listing rooms: {e}")
                active = []

            # launch or restart agents
            for room in active:
                proc = launched.get(room)
                if proc is None or proc.poll() is not None:
                    # --- Redis launch lock ---
                    launch_lock_key = f"agent_launch_lock:{room}"
                    launch_lock_val = str(uuid.uuid4())
                    have_lock = False
                    if redis_client:
                        have_lock = redis_client.set(launch_lock_key, launch_lock_val, nx=True, ex=LAUNCH_LOCK_TIMEOUT)
                        if not have_lock:
                            log(f"[manager] Skipping launch for {room}: launch lock held")
                            continue
                        else:
                            log(f"[manager] Acquired launch lock for {room}")
                    lock_renewal = None
                    try:
                        if have_lock and redis_client:
                            lock_renewal = asyncio.create_task(renew_lock_periodically(redis_client, launch_lock_key, launch_lock_val))
                        kill_main_py_for_room(room)
                        # Wait for all main.py processes for this room to terminate
                        for _ in range(20):  # wait up to 2 seconds
                            still_running = False
                            for p in psutil.process_iter(['pid', 'cmdline', 'environ']):
                                try:
                                    cmd = " ".join(p.info.get('cmdline') or [])
                                    if "main.py" in cmd:
                                        env = {}
                                        try:
                                            env = p.environ()
                                        except Exception:
                                            pass
                                        if env.get("LIVEKIT_ROOM") == room or room in cmd:
                                            still_running = True
                                            break
                                except Exception:
                                    continue
                            if not still_running:
                                break
                            time.sleep(0.1)
                        log(f"[manager] ▶ Launching {MAIN_SCRIPT} for room {room}")
                        env = os.environ.copy()
                        env["LIVEKIT_ROOM"] = room
                        p = subprocess.Popen(["python3", MAIN_SCRIPT], env=env, preexec_fn=os.setsid)  # Launch in its own process group
                        log(f"[manager] Launched main.py (PID {p.pid}) for room {room}")
                        launched[room] = p
                    finally:
                        if lock_renewal:
                            lock_renewal.cancel()
                        # Release launch lock
                        if redis_client and have_lock:
                            # Only release if we still hold the lock
                            val = redis_client.get(launch_lock_key)
                            if val and val.decode() == launch_lock_val:
                                redis_client.delete(launch_lock_key)
                                log(f"[manager] Released launch lock for {room}")
                    removal_times.pop(room, None)

            # schedule removals
            for room in list(launched):
                if room not in active and room not in removal_times:
                    log(f"[manager] Room {room} disappeared, scheduling termination in {GRACE_PERIOD}s")
                    removal_times[room] = now

            # terminate after grace period
            for room, t0 in list(removal_times.items()):
                if now - t0 > GRACE_PERIOD:
                    proc = launched.pop(room, None)
                    if proc:
                        log(f"[manager] ■ Terminating main.py for room {room} (PID {proc.pid})")
                        try:
                            os.killpg(proc.pid, signal.SIGTERM)  # Kill the entire process group
                        except Exception:
                            proc.terminate()
                    removal_times.pop(room, None)

            # warn if too many
            if len(launched) > 10:
                log(f"[manager] WARNING: {len(launched)} agents running!")

        except Exception as e:
            log(f"[manager] Unhandled exception: {e}")

        await asyncio.sleep(POLL_INTERVAL)

def shutdown(signum, frame):
    log("[manager] Shutting down, terminating all agents...")
    for room, proc in launched.items():
        log(f"[manager] Killing PID {proc.pid} for room {room}")
        try:
            os.killpg(proc.pid, signal.SIGTERM)  # Kill the entire process group
        except Exception:
            proc.terminate()
    sys.exit(0)

if __name__ == "__main__":
    try:
        cleanup_zombies()
    except Exception as e:
        print(f"[manager] Error during startup cleanup: {e}")

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        asyncio.run(manager())
    except KeyboardInterrupt:
        shutdown(None, None)

# No changes needed for manager.py; transfer and exit are handled by Agent1/main.py.