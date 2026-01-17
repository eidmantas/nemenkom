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

# Run the application
CMD ["python", "api/app.py"]
