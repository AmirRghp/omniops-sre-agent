FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for PostgreSQL and network healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and configurations
COPY . .

# Expose ports: 8000 for FastAPI API/SSE, 8001 for Chainlit Console
EXPOSE 8000 8001

# Default command starts the Chainlit interactive SRE console
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8001"]
