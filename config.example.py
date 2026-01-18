"""
Example configuration file
Copy this to config.py and fill in your API keys
"""

# Groq API Configuration
GROQ_API_KEY = ""  # Add your Groq API key here
GROQ_MODEL = "llama-3.3-70b-versatile"  # Higher quality model for better parsing of complex cases
# Alternative: "llama-3.1-8b-instant" for faster processing with better rate limits (14.4k RPD, 6k TPM, 500k TPD)
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Rate Limiting (Groq free tier limits)
GROQ_RATE_LIMIT_RPM = 30  # Requests per minute
GROQ_RATE_LIMIT_RPD = 14400  # Requests per day
