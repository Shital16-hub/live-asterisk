docker compose up -d

sleep 7

lk sip inbound create inbound-trunk.json --api-key APILodLwqNKJYqE --api-secret TIbzUfLfcCd6KZjZlGgbxnKqTsHBy7zDe5bzDe9gg3UB

lk sip dispatch create dispatch-rule.json --api-key APILodLwqNKJYqE --api-secret TIbzUfLfcCd6KZjZlGgbxnKqTsHBy7zDe5bzDe9gg3UB

# docker-compose exec asterisk asterisk -rx "sip show peers"
docker-compose logs -f --tail 100