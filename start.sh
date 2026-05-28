#!/bin/bash
set -e
exec python -m streamlit run streamlit_advisor.py \
    --server.port="${PORT:-8501}" \
    --server.address=0.0.0.0 \
    --server.headless=true
