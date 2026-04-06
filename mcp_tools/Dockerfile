# --------------------------------------------------------------------------
# IndiaMART MCP Server — Docker Image
# --------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY mcp_server.py .
COPY mcp_tools/ ./mcp_tools/

# Create volume mount point for database and .env
VOLUME ["/app/data"]
ENV DB_PATH=/app/data/leads.db

# MCP servers communicate via stdio, not HTTP ports
# The container is meant to be run with stdin/stdout attached
CMD ["python", "mcp_server.py"]
