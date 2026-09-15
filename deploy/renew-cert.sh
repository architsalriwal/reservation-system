#!/bin/bash
# Run via cron twice daily (Let's Encrypt's own recommendation) as root.
# Uses --webroot so nginx never needs to stop for a renewal - unlike the
# --standalone method used for the very first certificate, which needed
# port 80 free and briefly took the site down.
set -e
certbot renew --webroot -w /home/ubuntu/app/certbot-webroot --quiet
docker compose -f /home/ubuntu/app/docker-compose.prod.yml exec -T nginx nginx -s reload
