# Deployment Guide

This document explains how to deploy the Link Content Scraper to Fly.io with automatic staging deployments.

## Overview

- **Production**: Manual deployments to `link-content-scraper`
- **Staging**: Automatic deployments from `claude/**` branches to `link-content-scraper-staging`

## Prerequisites

1. [Fly.io account](https://fly.io/signup)
2. [Fly CLI installed](https://fly.io/docs/hands-on/install-flyctl/)
3. Anthropic API key

## Initial Setup

### 1. Create Production App

```bash
# Login to Fly.io
flyctl auth login

# Create production app (if not already created)
flyctl apps create link-content-scraper

# Set secrets
flyctl secrets set ANTHROPIC_API_KEY="your-key-here" --app link-content-scraper
```

### 2. Create Staging App

```bash
# Create staging app
flyctl apps create link-content-scraper-staging

# Set secrets for staging
flyctl secrets set ANTHROPIC_API_KEY="your-key-here" --app link-content-scraper-staging
```

### 3. Configure GitHub Secrets

Go to your GitHub repository settings and add these secrets:

**Settings → Secrets and variables → Actions → New repository secret**

1. **FLY_API_TOKEN**
   ```bash
   # Get your token
   flyctl auth token
   ```
   Copy the token and add it as `FLY_API_TOKEN` in GitHub

2. **ANTHROPIC_API_KEY**
   Add your Anthropic API key as `ANTHROPIC_API_KEY` in GitHub

## Deployment Workflows

### Automatic Staging Deployment

**Triggers:**
- Push to any `claude/**` branch
- Manual workflow dispatch

**What it does:**
1. Deploys to `link-content-scraper-staging`
2. Sets the `ANTHROPIC_API_KEY` secret
3. Comments on the commit with deployment URLs

**Staging URL:**
- Main: https://link-content-scraper-staging.fly.dev
- Agent: https://link-content-scraper-staging.fly.dev/agent

### Manual Production Deployment

```bash
# Deploy to production
flyctl deploy --config fly.toml --app link-content-scraper
```

Or create a production deployment workflow if desired.

## Testing on Staging

After pushing to a feature branch:

1. **Wait for deployment** (usually 2-3 minutes)
   - Check the Actions tab in GitHub
   - Look for the "Deploy to Fly.io Staging" workflow

2. **Access staging environment**
   - Main app: https://link-content-scraper-staging.fly.dev
   - AI Agent: https://link-content-scraper-staging.fly.dev/agent

3. **Test the features**
   - Try the classic scraper
   - Test the AI agent workflows
   - Verify API endpoints work

**Note:** Staging auto-suspends when idle and wakes on first request (may take a few seconds).

## Environment Configuration

### Production (`fly.toml`)
```toml
app = 'link-content-scraper'
primary_region = 'sea'

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = 'stop'
  auto_start_machines = true
  min_machines_running = 0
```

### Staging (`fly.staging.toml`)
```toml
app = 'link-content-scraper-staging'
primary_region = 'sea'

[env]
  FLY_ENV = "staging"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = 'suspend'  # More aggressive auto-suspend
  auto_start_machines = true
  min_machines_running = 0
```

## Secrets Management

Secrets are set via the Fly CLI:

```bash
# Production
flyctl secrets set ANTHROPIC_API_KEY="your-key" --app link-content-scraper

# Staging
flyctl secrets set ANTHROPIC_API_KEY="your-key" --app link-content-scraper-staging

# List secrets
flyctl secrets list --app link-content-scraper

# Remove secret
flyctl secrets unset ANTHROPIC_API_KEY --app link-content-scraper
```

## Monitoring

### View Logs

```bash
# Production logs
flyctl logs --app link-content-scraper

# Staging logs
flyctl logs --app link-content-scraper-staging

# Follow logs in real-time
flyctl logs --app link-content-scraper-staging -f
```

### Check Status

```bash
# Production status
flyctl status --app link-content-scraper

# Staging status
flyctl status --app link-content-scraper-staging

# View metrics
flyctl dashboard --app link-content-scraper-staging
```

## Cost Optimization

### Staging Environment
- Auto-suspends when idle (no cost when suspended)
- 1GB RAM, shared CPU
- Minimal cost when active (~$5-10/month with typical usage)

### Production Environment
- `min_machines_running = 0` allows full shutdown when idle
- Wakes automatically on requests
- Only pay for actual usage

## Troubleshooting

### Deployment Fails

1. **Check GitHub Action logs**
   - Go to Actions tab
   - Click on the failed workflow
   - Review error messages

2. **Common issues:**
   ```bash
   # App doesn't exist
   flyctl apps create link-content-scraper-staging

   # Missing FLY_API_TOKEN
   # Add it to GitHub secrets (Settings → Secrets)

   # Missing ANTHROPIC_API_KEY
   flyctl secrets set ANTHROPIC_API_KEY="key" --app link-content-scraper-staging
   ```

### App Won't Start

```bash
# Check logs
flyctl logs --app link-content-scraper-staging

# Check machine status
flyctl machine list --app link-content-scraper-staging

# Restart app
flyctl machine restart --app link-content-scraper-staging
```

### Agent Features Don't Work

```bash
# Verify ANTHROPIC_API_KEY is set
flyctl secrets list --app link-content-scraper-staging

# If missing, set it
flyctl secrets set ANTHROPIC_API_KEY="your-key" --app link-content-scraper-staging

# Check logs for API errors
flyctl logs --app link-content-scraper-staging -f
```

## Custom Domains (Optional)

### Production
```bash
flyctl certs create scraper.yourdomain.com --app link-content-scraper
```

### Staging
```bash
flyctl certs create staging.scraper.yourdomain.com --app link-content-scraper-staging
```

## Workflow Customization

### Deploy Only Specific Branches

Edit `.github/workflows/deploy-staging.yml`:

```yaml
on:
  push:
    branches:
      - 'claude/feature-*'  # Only branches starting with claude/feature-
      - 'claude/bugfix-*'   # And claude/bugfix-
```

### Add Production Deployment

Create `.github/workflows/deploy-production.yml`:

```yaml
name: Deploy to Production

on:
  push:
    branches:
      - main
  workflow_dispatch:

jobs:
  deploy:
    name: Deploy to Production
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - name: Deploy
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
        run: flyctl deploy --config fly.toml --app link-content-scraper
```

### Add Slack/Discord Notifications

Add to the workflow:

```yaml
- name: Notify Slack
  if: always()
  uses: slackapi/slack-github-action@v1
  with:
    payload: |
      {
        "text": "Staging deployed: https://link-content-scraper-staging.fly.dev/agent"
      }
  env:
    SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK }}
```

## Security Best Practices

1. **Never commit secrets**
   - Always use Fly secrets or GitHub secrets
   - Never hardcode API keys in code

2. **Rotate keys regularly**
   ```bash
   # Update API key
   flyctl secrets set ANTHROPIC_API_KEY="new-key" --app link-content-scraper
   ```

3. **Review GitHub Action logs**
   - Ensure no secrets are printed
   - Check for security warnings

4. **Use environment-specific keys**
   - Different API keys for staging vs production
   - Consider using test mode keys for staging

## Scaling

If you need more resources:

```bash
# Scale up
flyctl scale memory 2048 --app link-content-scraper
flyctl scale count 2 --app link-content-scraper

# Scale down
flyctl scale memory 1024 --app link-content-scraper
flyctl scale count 1 --app link-content-scraper
```

## Backup & Recovery

```bash
# Export app configuration
flyctl config save --app link-content-scraper

# Create volume snapshot (if using volumes)
flyctl volumes snapshots create <volume-id>

# Restore from config
flyctl deploy --config fly.toml
```

## Questions?

- [Fly.io Documentation](https://fly.io/docs/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Project Repository](https://github.com/JoshuaOliphant/Link-Content-Scraper)
