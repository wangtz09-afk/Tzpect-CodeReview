FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install pytest for running tests
RUN pip install pytest pytest-cov

# Copy application
COPY . .

# Create directories for output and logs
RUN mkdir -p /app/review-output /app/.code_review_logs /app/.checkpoints

# Set entrypoint
ENTRYPOINT ["python", "main.py"]
CMD ["--help"]

# Usage:
# docker build -t code-review-agent .
# docker run --env-file .env -v $(pwd)/results:/app/review-output code-review-agent review /repo --output-dir /app/review-output
