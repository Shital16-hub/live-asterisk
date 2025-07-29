# sendSipMsg.py

import sys
import socket
import random

# Usage: python sendSipMsg.py <to_extension> <message>
if len(sys.argv) < 3:
    print("Usage: python3 sendSipMsg.py <to_extension> <message>")
    sys.exit(1)

to_ext = sys.argv[1]
msg = sys.argv[2]

# SIP server details
SIP_SERVER = "15.204.51.230"
SIP_PORT = 5070

# Sender details (change as needed)
from_ext = "1000"
from_domain = SIP_SERVER

call_id = str(random.randint(100000, 999999))
cseq = random.randint(1, 10000)

sip_msg = f"""MESSAGE sip:{to_ext}@{SIP_SERVER}:{SIP_PORT} SIP/2.0
Via: SIP/2.0/UDP {from_domain}:5060;branch=z9hG4bK{random.randint(10000,99999)}
Max-Forwards: 70
To: <sip:{to_ext}@{SIP_SERVER}>
From: <sip:{from_ext}@{SIP_SERVER}:{SIP_PORT}>;tag={random.randint(10000,99999)}
Call-ID: {call_id}@{from_domain}
CSeq: {cseq} MESSAGE
Content-Type: text/plain
Content-Length: {len(msg)}

{msg}
"""

# Send SIP MESSAGE via UDP
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(sip_msg.encode(), (SIP_SERVER, SIP_PORT))
sock.close()

print(f"Sent SIP MESSAGE to {to_ext}: {msg}")