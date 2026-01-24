# TODO: Add separate test stage or CI/CD pipeline for running tests
# Tests are currently run locally via `make test` - not in Docker build
FROM python:3.14.1-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set PYTHONPATH so imports work
ENV PYTHONPATH=/app

# Expose port
EXPOSE 3333

# Run the web application
CMD ["python", "api/app.py"]
