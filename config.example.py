"""
Example configuration file
Copy this to config.py and fill in your API keys
DO NOT COMMIT config.py - it contains sensitive information
"""

# Groq API Configuration
GROQ_API_KEY = ""  # Add your Groq API key here
GROQ_MODEL = "llama-3.3-70b-versatile"  # Higher quality model for better parsing of complex cases
# Alternative: "llama-3.1-8b-instant" for faster processing with better rate limits (14.4k RPD, 6k TPM, 500k TPD)
# Note: Instant model can be used temporarily for bug fixing to save tokens
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Rate Limiting (Groq free tier limits)
# Conservative: Using 50% of free tier limits for safety
GROQ_RATE_LIMIT_RPM = 15  # Requests per minute (reduced from 30 for safety)
GROQ_RATE_LIMIT_RPD = 14400  # Requests per day
GROQ_RATE_LIMIT_TPM = 6000  # Tokens per minute
GROQ_RATE_LIMIT_TPD = 500000  # Tokens per day

# Safety margin (use 90% of limits to avoid hitting them)
GROQ_SAFETY_MARGIN = 0.9