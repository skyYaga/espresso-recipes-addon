#!/bin/sh
# Options (gaggiuino_url) are read by the app from /data/options.json.
export INGRESS_ONLY=1
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8099 --no-proxy-headers
