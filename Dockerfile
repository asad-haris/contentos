FROM python:3.11-slim

WORKDIR /app

# Copy requirements.txt first to leverage Docker cache
COPY requirements.txt .

# Install production dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application source code
COPY . .

# Expose port 8080 (default target for Cloud Run)
EXPOSE 8080

# Environment variable to define port fallback
ENV PORT 8080

# Launch Flask frontend application using gunicorn
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 frontend.app:app