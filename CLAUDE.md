# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Voicer Platform is an Arabic speech dataset collection system with multiple Gradio-based web applications for recording, administration, and data processing. The platform collects Arabic speech recordings from users across different Arab countries and dialects, storing data in Supabase (PostgreSQL) and AWS S3.

## Architecture

### Multi-App Structure

The repository contains separate Gradio applications running as systemd services:

- **main_app/**: Primary voice recording application (service: `voicer-main`)
  - User registration and authentication via Supabase
  - Sentence-by-sentence recording interface with progress tracking
  - Dialect-specific sentence pools loaded from JSON files (sentences_eg.json, sentences_ma.json, sentences_sa.json)
  - Records to AWS S3 with path structure: `{country_code}/{username}/wavs/{username}_{sentence_id}.wav`
  - Tracks user sessions, completed sentences, and total recording duration
  - Target: 30 minutes of recording per user (configurable via RECORDING_TARGET_MINUTES)

- **admin_app/**: Administrative dashboard (service: `voicer-admin`)
  - Separate admin authentication system with approval workflow (admins.approved column)
  - View and playback user recordings from S3
  - Statistics and analytics with matplotlib visualizations (gender, dialect, country distributions)
  - Progress tracking against recording targets
  - Downloads audio directly from S3 to avoid Gradio URL issues

- **stats_app/**: Placeholder/utility app

### Database Schema (Supabase)

**users table:**
- username, name, email, country, dialect_code, gender, age, created_at

**sessions table:**
- username, completed_sentences (array), total_recording_duration

**admins table:**
- name, email, password (hashed), approved (boolean), created_at

### Storage (AWS S3)

- Bucket: `voicer-storage` (configurable via S3_BUCKET)
- Region: `me-south-1` (configurable via AWS_REGION)
- Path structure: `{country_code}/{username}/wavs/{username}_{sentence_id}.wav`
- Authentication: IAM role preferred, fallback to AWS_ACCESS_KEY/AWS_SECRET_KEY

## Development Commands

### Environment Setup

```bash
# Python environment is managed via conda
# Environment path: /home/ubuntu/miniconda3/envs/voicer-env (on production)
# Local development:
pip install -r requirements.txt
```

### Running Applications Locally

**Native Python:**
```bash
# Main recording app (default port 7860)
python main_app/app.py

# Admin dashboard (default port 7861)
python admin_app/app.py
```

**Docker (recommended):**
```bash
# Using docker-compose (both services)
docker-compose up -d

# Individual services
docker-compose up -d voicer-main    # Port 7860
docker-compose up -d voicer-admin   # Port 7861

# View logs
docker-compose logs -f voicer-main
docker-compose logs -f voicer-admin

# Stop services
docker-compose down
```

See [DOCKER.md](DOCKER.md) for comprehensive Docker setup and Railway deployment instructions.

### Deployment

**Traditional (systemd on Ubuntu server):**

Deployment uses bash scripts that interact with systemd services on the production server:

```bash
# Deploy main app (voicer-main service)
./deploy-main.sh

# Deploy admin app (voicer-admin service)
./deploy-admin.sh

# Deployment flags:
# f = force restart (even without code changes)
# r = force reinstall requirements.txt
./deploy-main.sh f r  # Force restart and reinstall deps
```

**Note:** `deploy-youtube.sh` exists but is deprecated as the YouTube service has been removed.

**Deployment process:**
1. Detects previous commit via git
2. Pulls latest from origin/main with hard reset
3. Checks for changes (skips if no changes and no force flags)
4. Conditionally installs requirements.txt if changed or forced
5. Reloads systemd daemon
6. Restarts specified service(s)
7. Verifies service status
8. Logs deployment to /home/ubuntu/.voicer/deploy.log

**Production paths:**
- App directory: `/opt/voicer-platform`
- Python: `/home/ubuntu/miniconda3/envs/voicer-env/bin/python`
- Services: `voicer-main`, `voicer-admin` (managed by systemd)

**Docker/Railway deployment:**

Each service has its own Dockerfile:
- `Dockerfile.main` - Main recording app
- `Dockerfile.admin` - Admin dashboard

Railway deployment steps:
1. Push code to GitHub
2. Create Railway project and add services
3. For each service, configure Dockerfile path in Railway settings
4. Set environment variables (see below)
5. Railway auto-builds and deploys on git push

See [DOCKER.md](DOCKER.md) for detailed instructions.

## Environment Variables

**Main App (voicer-main):**
```bash
SUPABASE_URL=
SUPABASE_KEY=  # Anon key
AWS_ACCESS_KEY=  # Optional if using IAM role
AWS_SECRET_KEY=  # Optional if using IAM role
S3_BUCKET=voicer-storage
AWS_REGION=me-south-1
```

**Admin App (voicer-admin):**
```bash
SUPABASE_URL=
SUPABASE_KEY=  # Anon key (fallback)
SUPABASE_SERVICE_ROLE_KEY=  # Service role key (preferred for admin operations)
AWS_ACCESS_KEY=  # Optional if using IAM role
AWS_SECRET_KEY=  # Optional if using IAM role
S3_BUCKET=voicer-storage
AWS_REGION=me-south-1
GRADIO_ADMIN_PORT=7861
```

Load via python-dotenv from `.env` file (not checked into git).

## Key Implementation Details

### Country and Dialect System

20 Arab countries supported with country-specific dialect options. Main countries with sentence pools:
- Egypt (eg): 2.3MB sentences_eg.json
- Morocco (ma): 2.1MB sentences_ma.json
- Saudi Arabia (sa): 14MB sentences_sa.json

Dialects stored as codes (e.g., "ar-EG-ca" for Cairo Egyptian) combining ISO codes and custom dialect identifiers.

### Audio Recording

- Format: WAV files via soundfile library
- Gradio Audio component captures browser microphone input
- Files uploaded to S3 immediately after recording
- Session state tracks progress to prevent duplicate recordings

### Authentication

- **Users**: Supabase-based with username/email/password
- **Admins**: Separate table with manual approval workflow (approved column must be true)
- Passwords hashed using werkzeug.security

### Admin Dashboard Features

- Audio preview uses direct S3 download (sr, numpy_array) to avoid Gradio URL issues
- Presigned URLs generated for markdown links (1 hour expiration)
- Country filtering for focused statistics
- Dual-mode statistics: cross-country overview vs per-country detailed view
- Progress charts compare achieved vs target recording time

### Sentence Management

Large JSON files with structure:
```json
{
  "sentences": [
    {"unique_id": "001", "text": "sentence text"}
  ]
}
```

Loaded at app startup and filtered per user's completed sentences to avoid repeats.

## Common Patterns

1. **S3 Error Handling**: Always check for IAM role first, fallback to explicit keys
2. **Supabase Queries**: Use `.select().eq().execute()` pattern, check `resp.data`
3. **Gradio State**: Store user session in `gr.State` dict to maintain context across interactions
4. **Deployment**: Always use deployment scripts, never manual git operations on production
5. **Service Management**: Use systemd for process management (restart, status checks)

## Git Workflow

- Main branch: `main` (all deploys pull from origin/main)
- Deployment tracking: `.last_deploy_commit` file stores last deployed commit hash
- Recent commits show incremental deployment improvements and service-specific deploys
