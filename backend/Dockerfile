FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies needed by psycopg2 and binary downloads
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install github-mcp-server binary (v1.2.0, verified asset: github-mcp-server_Linux_x86_64.tar.gz)
# Bump GITHUB_MCP_VERSION to upgrade; --version verifies the binary runs and fails the build fast if not.
ARG GITHUB_MCP_VERSION=v1.2.0
RUN curl -fsSL \
      "https://github.com/github/github-mcp-server/releases/download/${GITHUB_MCP_VERSION}/github-mcp-server_Linux_x86_64.tar.gz" \
    | tar xz -C /usr/local/bin github-mcp-server \
    && github-mcp-server --version

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose API port
EXPOSE 8000

# Default command (overridden by docker-compose for --reload).
# Railway injects $PORT at runtime; fall back to 8000 for local docker-compose.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
