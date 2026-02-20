FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (for pdfplumber, etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
COPY config/ ./config/

# Install the project
RUN pip install --no-cache-dir -e .

# Create data directory for SQLite
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "-m", "src"]
