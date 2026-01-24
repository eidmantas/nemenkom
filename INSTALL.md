# Installation Guide

This guide will help you set up the Nemenčinė waste schedule system.

## Prerequisites

- Docker and Docker Compose (or Podman and Podman Compose)
- Python 3.14+ (for local development)
- Google Cloud Platform account (for Google Calendar integration)
- Groq API account (for AI parsing)

## Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd nemenkom
   ```

2. **Set up secrets** (see [Secrets Setup](#secrets-setup) below)

3. **Build and run**
   ```bash
   make build
   make up
   ```

4. **Access the application**
   - Web UI: http://localhost:3333
   - API Docs: http://localhost:3333/apidocs

## Secrets Setup

The application requires several secret files in the `secrets/` directory. These files are **NOT** committed to git for security reasons.

### Required Secret Files

Create the following files in the `secrets/` directory:

#### 1. `api_key.txt`
- **Purpose**: API authentication key for the REST API
- **Format**: Single line with your API key (no quotes, no whitespace)
- **Example**: `your-api-key-here`
- **How to generate**: Use a secure random string generator
  ```bash
  # Generate a secure API key
  openssl rand -hex 32 > secrets/api_key.txt
  ```

#### 2. `groq_api_key.txt`
- **Purpose**: Groq API key for AI-powered parsing of complex location patterns
- **Format**: Single line with your Groq API key
- **How to get**: 
  1. Sign up at https://console.groq.com/
  2. Create an API key in the dashboard
  3. Copy the key to `secrets/groq_api_key.txt`
- **Note**: Free tier includes 14,400 requests/day

#### 3. `credentials.json`
- **Purpose**: Google Service Account credentials for Calendar API access
- **Format**: JSON file from Google Cloud Platform
- **How to get**:
  1. Go to [Google Cloud Console](https://console.cloud.google.com/)
  2. Create a new project (or select existing)
  3. Enable "Google Calendar API"
  4. Create a Service Account:
     - Go to "IAM & Admin" → "Service Accounts"
     - Click "Create Service Account"
     - Give it a name (e.g., "nemenkom-calendar")
     - Grant it "Editor" role (or "Calendar Admin" for more permissions)
  5. Create a JSON key:
     - Click on the service account
     - Go to "Keys" tab
     - Click "Add Key" → "Create new key"
     - Select "JSON" format
     - Download the file
     - Save it as `secrets/credentials.json`
  6. **Important**: Share your Google Calendar with the service account email:
     - The service account email is in the JSON file (field: `client_email`)
     - Go to your Google Calendar settings
     - Share the calendar with this email address
     - Give it "Make changes to events" permission

### Secret Files Structure

After setup, your `secrets/` directory should look like:
```
secrets/
├── .gitkeep              # Git placeholder (keeps directory in git)
├── api_key.txt          # Your API key
├── groq_api_key.txt     # Your Groq API key
└── credentials.json     # Google Service Account credentials
```

### Verification

To verify your secrets are set up correctly:

```bash
# Check if all required files exist
ls -la secrets/

# Test configuration loading (will error if secrets are missing)
python -c "import config; print('✅ All secrets loaded successfully')"
```

## Docker Setup

### Volume Mounts

Both the `secrets/` directory and `config.py` are mounted as **read-only volumes** in Docker containers. This means:
- Secrets and config are **not** copied into Docker images (more secure)
- Secrets and config must exist on the host machine
- Changes to secrets/config require container restart

### Docker Compose Configuration

The `docker-compose.yaml` mounts both the secrets directory and config file:
```yaml
volumes:
  - ./secrets:/app/secrets:ro  # Read-only mount
  - ./config.py:/app/config.py:ro  # Read-only mount (not baked into image)
```

**Note**: `config.py` is also in `.gitignore` and should not be committed. Copy `config.example.py` to `config.py` and customize it for your environment.

## Development Setup

For local development without Docker:

1. **Create virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up secrets** (same as above)

4. **Run locally**
   ```bash
   # Run API server
   python api/app.py

   # Run scraper
   python scraper/scheduler.py
   ```

## Troubleshooting

### Error: "Secret file not found"

**Problem**: A required secret file is missing.

**Solution**: 
1. Check that all required files exist in `secrets/` directory
2. Verify file names match exactly (case-sensitive)
3. See [Secrets Setup](#secrets-setup) above

### Error: "Secret file is empty"

**Problem**: A secret file exists but is empty.

**Solution**: Add your API key/credentials to the file. See [Secrets Setup](#secrets-setup) above.

### Error: "Calendar usage limits exceeded"

**Problem**: Google Calendar API quota exceeded.

**Solution**: 
- Wait for quota to reset (daily limit)
- The background worker will automatically retry every 5 minutes
- Consider upgrading Google Cloud project quota if needed

### Error: "Rate Limit Exceeded"

**Problem**: Too many API requests too quickly.

**Solution**: 
- The system automatically retries with 5-minute intervals
- Wait for rate limits to reset
- For Groq API: Check your rate limits at https://console.groq.com/

## Security Notes

- **Never commit** `secrets/` directory to git (already in `.gitignore`)
- **Never commit** `config.py` to git (contains loaded secrets)
- Use strong, randomly generated API keys
- Restrict Google Service Account permissions to minimum required
- Rotate API keys periodically
- Use read-only volume mounts in production

## Next Steps

After installation:
1. Run the scraper to populate the database: `make run-scraper`
2. Check API health: `curl http://localhost:3333/api/v1/villages`
3. View web interface: http://localhost:3333
4. Check calendar creation status in logs: `make logs-scraper`

## Additional Resources

- [Architecture Documentation](documentation/ARCHITECTURE.md)
- [Design Change Documentation](documentation/DESIGN-CHANGE.md)
- [API Documentation](http://localhost:3333/apidocs) (when running)
