#!/bin/bash

docker-compose down -v #&& docker-compose up -d && 
docker-compose up -d livekit
sleep 1
docker-compose up -d redis
sleep 1
docker-compose up -d caddy
sleep 1
docker-compose up -d egress
sleep 1
docker-compose up -d ingress
sleep 1
docker-compose up -d asterisk
sleep 1
docker-compose up -d sip
sleep 1
docker-compose up -d qdrant
sleep 1
docker-compose up -d rag
sleep 1
clear

redis-cli -u redis://2123tt@15.204.51.230:6379 <<<"FLUSHALL"
lk sip inbound create inbound-trunk.json --api-key APILodLwqNKJYqE --api-secret TIbzUfLfcCd6KZjZlGgbxnKqTsHBy7zDe5bzDe9gg3UB
lk sip dispatch create dispatch-rule.json --api-key APILodLwqNKJYqE --api-secret TIbzUfLfcCd6KZjZlGgbxnKqTsHBy7zDe5bzDe9gg3UB
lk sip outbound create outbound-trunk.json --api-key APILodLwqNKJYqE --api-secret TIbzUfLfcCd6KZjZlGgbxnKqTsHBy7zDe5bzDe9gg3UB

rm -rf /root/livekit.ecommcube.com/ai-agent/logs/*
rm -rf /root/livekit.ecommcube.com/ai-agent/transcriptions/*
rm -rf /root/livekit.ecommcube.com/ai-agent/__pycache__/*

python3 ai-agent/manager.py


