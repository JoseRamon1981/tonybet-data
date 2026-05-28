#!/bin/bash
set -e
PORT="${PORT:-8080}"
exec python -m streamlit run streamlit_advisor.py \
    --server.port="$PORT" \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
