#!/usr/bin/env python3
import sys
import redis

def main():
    if len(sys.argv) < 3:
        sys.exit(1)
    room_name = sys.argv[1]
    member_name = sys.argv[2]
    r = redis.Redis(host='localhost', port=6379, db=0)
    r.setex(f'room_member:{room_name}', 3600, member_name)

if __name__ == "__main__":
    main() 