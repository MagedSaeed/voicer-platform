# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Voicer Platform is an Arabic speech dataset collection system with multiple Gradio-based web applications for recording, administration, annotation, and data processing. Data is stored in Supabase (PostgreSQL) and AWS S3.

## Architecture

### Multi-App Structure

Four separate Gradio apps, each with its own Dockerfile and systemd service:

| App | Port | Service | Dockerfile | Purpose |
|-----|------|---------|------------|---------|
| **main_app/** | 7860 | `voicer-main` | `Dockerfile.main` | Voice recording (user-facing) |
| **admin_app/** | 7861 | `voicer-admin` | `Dockerfile.admin` | Admin dashboard & analytics |
| **annotate_app/** | 7862 | `voicer-annotate` | `Dockerfile.annotate` | Audio quality annotation |
| **stats_app/** | — | — | — | Placeholder/unused |

No shared code between apps — each has its own S3 client, Supabase client, and country mappings.

### Two Separate Supabase Instances

- **main_app and admin_app** use `SUPABASE_URL` / `SUPABASE_KEY`
- **annotate_app** uses `SUPABASE_URL_2` / `SUPABASE_KEY_2` (a separate Supabase project)

### Database Schema

**Main Supabase instance** (main_app, admin_app):
- `users`: username, name, email, country, dialect_code, gender, age, created_at
- `sessions`: username, completed_sentences (array), total_recording_duration
- `admins`: name, email, password (hashed), approved (boolean), created_at

**Annotation Supabase instance** (annotate_app):
- `annotators`: name (unique identifier for annotation workers)
- `annotations`: sample_id, country_code, country_name, s3_audio_key, audio_file, text_sample, annotator_name, decision (accept/reject), reject_reason, comment

### Storage (AWS S3)

- Bucket: `voicer-storage` (S3_BUCKET), Region: `me-south-1` (AWS_REGION)
- Path: `{country_code}/{username}/wavs/{username}_{sentence_id}.wav`
- Metadata: `{country_code}/{username}/metadata.csv` (and optional `metadata_oth.csv`)
- Auth: IAM role preferred, fallback to AWS_ACCESS_KEY/AWS_SECRET_KEY

## Development Commands

### Setup and Run

```bash
pip install -r requirements.txt

# Run individual apps
python main_app/app.py       # Port 7860
python admin_app/app.py      # Port 7861
python annotate_app/app.py   # Port 7862 (uses PORT env var)
```

### Docker

```bash
docker-compose up -d                      # All services
docker-compose up -d voicer-main          # Just main app
docker-compose up -d voicer-annotate      # Just annotation tool
docker-compose logs -f voicer-main        # View logs
docker-compose down                       # Stop all
```

See [DOCKER.md](DOCKER.md) for Railway deployment instructions.

### Production Deployment (systemd)

```bash
./deploy-main.sh          # Deploy main app
./deploy-admin.sh          # Deploy admin app
./deploy-main.sh f r       # Force restart + reinstall deps
```

Deployment scripts: git pull → conditional pip install → systemd restart → verify status. Logs to `/home/ubuntu/.voicer/deploy.log`.

**Production paths:** App at `/opt/voicer-platform`, Python at `/home/ubuntu/miniconda3/envs/voicer-env/bin/python`.

**Note:** annotate_app does not yet have a deploy script or systemd service — Docker only for now.

### CI/CD

GitHub Actions workflows in `.github/workflows/`:
- `deploy-main.yml`: Triggers on push to main when `main_app/**` changes → SSHs to server → runs `deploy-main.sh`
- `deploy-admin.yml`: Triggers on push to main when `admin_app/**` changes → SSHs to server → runs `deploy-admin.sh`

No test suite or linting configuration exists in the project.

## Environment Variables

All apps load from `.env` via python-dotenv. See `.env.example` for template.

```bash
# Shared (all apps)
AWS_ACCESS_KEY=
AWS_SECRET_KEY=
S3_BUCKET=voicer-storage
AWS_REGION=me-south-1

# Main & Admin apps
SUPABASE_URL=
SUPABASE_KEY=                    # Anon key
SUPABASE_SERVICE_ROLE_KEY=       # Admin app prefers this

# Annotate app (separate Supabase project)
SUPABASE_URL_2=
SUPABASE_KEY_2=

# Ports
GRADIO_ADMIN_PORT=7861
PORT=7862                        # Annotate app port
```

## Key Implementation Details

### Country System

20 country codes defined in COUNTRY_CODES dict, but only 11 have sentence JSON files in `main_app/`: eg, sa, ma, ye, jo, ps, dz, sd, tn, sy, ae. Sentence files range from 23KB (Sudan) to 14MB (Saudi Arabia).

Sentence JSON structure:
```json
{"sentences": [{"unique_id": "96259", "text": "...", "dialect": [], "source": "", "source_dialect": ""}]}
```

### Annotation Tool (annotate_app)

- Reads metadata CSVs from S3 (handles both comma and pipe delimiters)
- Randomly samples unannotated audio (RANDOM_TRIES=150, chunked Supabase queries at SUPABASE_IN_CHUNK=100)
- Keyboard hotkeys: A=accept, R=reject, N=submit & next
- Reject reasons: Noisy, Wrong text, Silence, Clipped/Cut, Distortion, Wrong speaker, Other

### Common Patterns

1. **S3 client creation**: Check for IAM role first, fallback to explicit keys
2. **Supabase queries**: `.select().eq().execute()` pattern, check `resp.data`
3. **Gradio state**: `gr.State` dict maintains user session context across interactions
4. **Audio handling**: Direct S3 download via soundfile (sr, numpy_array) — not Gradio URLs

## Git Workflow

- Main branch: `main` (all deploys pull from origin/main)
- `.last_deploy_commit` tracks last deployed commit hash
- CI auto-deploys on push to main for changed apps
