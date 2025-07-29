import os
import sys
import time
import uuid
import requests
import jwt
import logging
from dotenv import load_dotenv
import redis
from time import sleep

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("AgentCaller")

load_dotenv()

LIVEKIT_API_KEY    = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
LIVEKIT_REST_URL   = os.getenv("LIVEKIT_REST_URL", os.getenv("LIVEKIT_URL_HTTPS", "http://localhost:7880").replace("wss://", "https://").replace("ws://", "http://"))
SIP_TRUNK_ADDRESS  = os.getenv("SIP_TRUNK_ADDRESS",  "15.204.51.230:5070")
SIP_TRUNK_USER     = os.getenv("SIP_TRUNK_USER",     "livekitgw")
SIP_TRUNK_PASS     = os.getenv("SIP_TRUNK_PASS",     "passgw")
SIP_EXTENSION      = os.getenv("SIP_EXTENSION",      "3000") # to create a new trunk

ROOM_NAME = os.getenv("LIVEKIT_ROOM")

# Allow room name override via CLI
if len(sys.argv) > 1:
    ROOM_NAME = sys.argv[1]


def generate_jwt():
    payload = {
        "iss": LIVEKIT_API_KEY,
        "sub": "sip-service",
        "exp": int(time.time()) + 3600,
        "sip": {
            "call": True,
            "admin": True
        }
    }
    return jwt.encode(payload, LIVEKIT_API_SECRET, algorithm="HS256")


def headers():
    return {
        "Authorization": f"Bearer {generate_jwt()}",
        "Content-Type": "application/json",
    }


def list_trunks():
    """List all SIP outbound trunks and return them as a list."""
    url_list = f"{LIVEKIT_REST_URL}/twirp/livekit.SIP/ListSIPOutboundTrunk"
    r = requests.post(url_list, headers=headers(), json={})
    if r.status_code == 200:
        return r.json().get("items") or r.json().get("sip_trunks", [])
    else:
        logger.error(f"Failed to list trunks: {r.status_code} {r.text}")
        return []


def get_or_create_trunk():
    trunks = list_trunks()
    for trunk in trunks:
        if trunk.get("address") == SIP_TRUNK_ADDRESS:
            logger.info(f"Found existing trunk: {trunk['sip_trunk_id']}")
            return trunk["sip_trunk_id"]
    # Create trunk if not found
    name = "AsteriskTrunk-" + str(uuid.uuid4())[:8]
    body = {
        "trunk": {
            "name":         name,
            "address":      SIP_TRUNK_ADDRESS,
            "auth_username":SIP_TRUNK_USER,
            "auth_password":SIP_TRUNK_PASS,
            "numbers":      [ SIP_EXTENSION ],
        }
    }
    url_create = f"{LIVEKIT_REST_URL}/twirp/livekit.SIP/CreateSIPOutboundTrunk"
    r = requests.post(url_create, headers=headers(), json=body)
    logger.info(f"CreateSIPOutboundTrunk response: {r.status_code} {r.text}")
    r.raise_for_status()
    return r.json()["sip_trunk_id"]


def join_sip_participant(trunk_id, extension, room_name, identity=None):
    logger.info(f"[Join] Attempting to join extension {extension} to room {room_name} using trunk {trunk_id}")
    payload = {
        "sip_trunk_id": trunk_id,
        "sip_call_to": extension,
        "room_name": room_name,
        "participant_identity": identity or f"sip-{extension}-{uuid.uuid4().hex[:6]}",
        "headers": {"X-Room-Name": room_name}
    }
    url = f"{LIVEKIT_REST_URL}/twirp/livekit.SIP/CreateSIPParticipant"
    try:
        r = requests.post(url, headers=headers(), json=payload)
        logger.info(f"[Join] SIP participant {extension} join response: {r.status_code} {r.text}")
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"[Join] Failed to join SIP participant {extension} to room {room_name}: {e}")
        return False


def get_current_room_name():
    r = redis.Redis(host='localhost', port=6379, db=0)
    value = r.get('current_room_name')
    if value:
        room = value.decode()
        logger.info(f"[RoomName] Fetched current_room_name from Redis: {room}")
        return room
    else:
        logger.error("[RoomName] No current_room_name found in Redis, using default ROOM_NAME")
        return ROOM_NAME


def remove_sip_participant(room_name, participant_identity):
    url = f"{LIVEKIT_REST_URL}/twirp/livekit.SIP/DeleteSIPParticipant"
    payload = {
        "room_name": room_name,
        "participant_identity": participant_identity,
    }
    try:
        r = requests.post(url, headers=headers(), json=payload)
        if r.status_code != 200:
            logger.error(f"Failed to remove SIP participant: {r.status_code} {r.text}")
        else:
            logger.info(f"Removed SIP participant {participant_identity} from room {room_name}")
    except Exception as e:
        logger.error(f"Exception removing SIP participant: {e}")


# def main():
#     logger.info(f"Using trunk_id: {list_trunks()}")
#     trunk_id = get_or_create_trunk()
#     logger.info(f"Using trunk_id: {trunk_id}")
#     # Fetch the latest room name from Redis before each join
#     room_name = get_current_room_name()
#     for ext in [SIP_EXTENSION, "3000"]:
#         logger.info(f"[Main] Calling {ext} to join room {room_name}")
#         success = join_sip_participant(trunk_id, ext, room_name)
#         if not success:
#             logger.error(f"[Main] Failed to join {ext} to room {room_name}")
#         else:
#             logger.info(f"[Main] Successfully joined {ext} to room {room_name}")


# if __name__ == "__main__":
#     main() 
