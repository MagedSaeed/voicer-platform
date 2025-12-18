# Docker Deployment Guide

This guide covers how to run the Voicer Platform using Docker locally and deploy to Railway.app.

## Architecture

The platform consists of three independent services:
- **voicer-main**: Main voice recording app (port 7860)
- **voicer-admin**: Admin dashboard (port 7861)
- **voicer-youtube**: YouTube transcript scraper (port 7862 locally, 7860 in container)

Each service has its own Dockerfile:
- `Dockerfile` or `Dockerfile.main` - Main recording app
- `Dockerfile.admin` - Admin dashboard
- `Dockerfile.youtube` - YouTube scraper

## Local Development with Docker Compose

### Prerequisites
- Docker and Docker Compose installed
- Supabase account with database tables set up
- AWS S3 bucket configured

### Setup

1. **Create environment file:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` with your credentials:**
   ```bash
   # Required for all services
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-anon-key
   SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

   # Required for main and admin apps
   AWS_ACCESS_KEY=your-aws-access-key
   AWS_SECRET_KEY=your-aws-secret-key
   S3_BUCKET=voicer-storage
   AWS_REGION=me-south-1
   ```

3. **Start all services:**
   ```bash
   docker-compose up -d
   ```

4. **Start specific service:**
   ```bash
   docker-compose up -d voicer-main
   docker-compose up -d voicer-admin
   docker-compose up -d voicer-youtube
   ```

5. **View logs:**
   ```bash
   docker-compose logs -f voicer-main
   docker-compose logs -f voicer-admin
   ```

6. **Stop services:**
   ```bash
   docker-compose down
   ```

### Access Applications

- Main Recording App: http://localhost:7860
- Admin Dashboard: http://localhost:7861
- YouTube Scraper: http://localhost:7862

## Building Individual Services

### Main App
```bash
docker build -f Dockerfile.main -t voicer-main .
docker run -p 7860:7860 --env-file .env voicer-main
```

### Admin App
```bash
docker build -f Dockerfile.admin -t voicer-admin .
docker run -p 7861:7861 --env-file .env voicer-admin
```

### YouTube App
```bash
docker build -f Dockerfile.youtube -t voicer-youtube .
docker run -p 7860:7860 voicer-youtube
```

## Railway.app Deployment

Railway will automatically detect the Dockerfiles and allow you to deploy each service separately.

### Deployment Steps

1. **Push your code to GitHub**

2. **Create a new project on Railway.app**

3. **Deploy each service:**
   - Click "New Service" → "GitHub Repo"
   - Select your repository
   - Railway will detect `Dockerfile` by default

4. **For multiple services:**
   - Deploy first service with `Dockerfile` (main app)
   - Add new service → Select same repo → Configure settings
   - Under "Settings" → "Build" → Set custom Dockerfile path:
     - Admin: `Dockerfile.admin`
     - YouTube: `Dockerfile.youtube`

5. **Configure Environment Variables:**

   For each service in Railway dashboard, add these variables:

   **Main App (voicer-main):**
   ```
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-anon-key
   AWS_ACCESS_KEY=your-access-key
   AWS_SECRET_KEY=your-secret-key
   S3_BUCKET=voicer-storage
   AWS_REGION=me-south-1
   GRADIO_SERVER_NAME=0.0.0.0
   GRADIO_SERVER_PORT=7860
   ```

   **Admin App (voicer-admin):**
   ```
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
   SUPABASE_KEY=your-anon-key
   AWS_ACCESS_KEY=your-access-key
   AWS_SECRET_KEY=your-secret-key
   S3_BUCKET=voicer-storage
   AWS_REGION=me-south-1
   GRADIO_SERVER_NAME=0.0.0.0
   GRADIO_SERVER_PORT=7861
   GRADIO_ADMIN_PORT=7861
   ```

   **YouTube App (voicer-youtube):**
   ```
   GRADIO_SERVER_NAME=0.0.0.0
   GRADIO_SERVER_PORT=7860
   ```

6. **Railway will automatically:**
   - Build your Docker image
   - Deploy the container
   - Provide a public URL (e.g., `your-app.railway.app`)
   - Auto-redeploy on git push

### Railway Service Configuration

Each Railway service should use:
- **Build Method**: Dockerfile
- **Dockerfile Path**:
  - Main: `Dockerfile` or `Dockerfile.main`
  - Admin: `Dockerfile.admin`
  - YouTube: `Dockerfile.youtube`
- **Port**: Railway auto-detects from EXPOSE directive (7860 or 7861)

## Troubleshooting

### Port conflicts locally
If ports are already in use, modify the port mapping in `docker-compose.yml`:
```yaml
ports:
  - "8860:7860"  # Host:Container
```

### Audio not working in Docker
The apps capture audio through browser microphone, so audio recording should work regardless of Docker environment.

### S3 connection issues
- Verify AWS credentials are correct
- Ensure S3 bucket exists and region is correct
- Check IAM permissions for S3 read/write access

### Supabase connection issues
- Verify Supabase URL and keys
- Check that tables exist: `users`, `sessions`, `admins`

### Railway deployment fails
- Check Railway build logs for errors
- Verify Dockerfile path is correct in service settings
- Ensure all required environment variables are set
- Check that Python version 3.12 is compatible with all dependencies

## Production Considerations

1. **Environment Variables**: Never commit `.env` file to git
2. **S3 Bucket**: Use separate buckets for dev/prod
3. **Supabase**: Use separate projects for dev/prod
4. **CORS**: Configure Gradio for your domain if needed
5. **Health Checks**: Railway provides automatic health monitoring
6. **Logs**: Use Railway dashboard or `docker-compose logs` locally

## Notes

- The main app requires sentence JSON files (`sentences_*.json`) which are included in the Docker image
- Admin app downloads audio directly from S3 to avoid Gradio URL issues
- YouTube app works independently and doesn't require database/S3
- All apps use Gradio's built-in server (no nginx needed)
