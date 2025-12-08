# 🚀 Quick Setup Guide for Staging Deployment

Your staging deployment is **almost** ready! Just a few quick steps to enable automatic deployments.

## What You Get

✅ Automatic deployments from feature branches (`claude/**`)
✅ Staging URL: https://link-content-scraper-staging.fly.dev/agent
✅ Test on the go from any device
✅ Cost-optimized (auto-suspends when idle)
✅ Isolated from production

## Setup (5 minutes)

### Step 1: Create Staging App on Fly.io

```bash
# Login to Fly.io (if you haven't already)
flyctl auth login

# Create the staging app
flyctl apps create link-content-scraper-staging

# Set the Anthropic API key for staging
flyctl secrets set ANTHROPIC_API_KEY="your-anthropic-api-key" \
  --app link-content-scraper-staging
```

### Step 2: Add GitHub Secrets

Go to: **GitHub.com → Your Repo → Settings → Secrets and variables → Actions**

#### Add these two secrets:

**1. FLY_API_TOKEN**
```bash
# Get your Fly.io API token
flyctl auth token
```
Copy the output and create a new secret:
- Name: `FLY_API_TOKEN`
- Value: (paste the token)

**2. ANTHROPIC_API_KEY**
Create another secret:
- Name: `ANTHROPIC_API_KEY`
- Value: (your Anthropic API key)

### Step 3: Test It!

The GitHub Action has already been pushed and should have run (or is running).

**Check the deployment:**
1. Go to: **GitHub.com → Your Repo → Actions tab**
2. Look for "Deploy to Fly.io Staging" workflow
3. If it failed (because secrets weren't set), click "Re-run all jobs"

**Once successful:**
- Visit: https://link-content-scraper-staging.fly.dev/agent
- Try the AI agent features!

## How It Works

### Automatic Deployment

Every time you push to a `claude/**` branch:
1. GitHub Action triggers automatically
2. Builds and deploys to staging
3. Sets environment secrets
4. Comments on your commit with URLs

### Staging Environment

- **URL:** https://link-content-scraper-staging.fly.dev
- **Agent UI:** https://link-content-scraper-staging.fly.dev/agent
- **Auto-suspend:** Yes (wakes on first request, ~3 seconds)
- **Cost:** ~$0 when idle, ~$5-10/month with regular use

## Testing Your Changes

```bash
# Make changes to your code
git add .
git commit -m "Add new feature"

# Push to your claude branch
git push origin claude/your-branch-name

# Wait ~2-3 minutes for deployment
# Then visit: https://link-content-scraper-staging.fly.dev/agent
```

## Troubleshooting

### Deployment Failed

**Check GitHub Action logs:**
1. Go to Actions tab
2. Click the failed workflow
3. Review error messages

**Common fixes:**

```bash
# App doesn't exist
flyctl apps create link-content-scraper-staging

# Missing secrets
# Go to: GitHub Settings → Secrets → Actions
# Add: FLY_API_TOKEN and ANTHROPIC_API_KEY
```

### Staging App Won't Start

```bash
# Check logs
flyctl logs --app link-content-scraper-staging

# Check status
flyctl status --app link-content-scraper-staging

# Restart if needed
flyctl machine restart --app link-content-scraper-staging
```

### AI Agent Features Don't Work

```bash
# Verify API key is set
flyctl secrets list --app link-content-scraper-staging

# If missing, set it
flyctl secrets set ANTHROPIC_API_KEY="your-key" \
  --app link-content-scraper-staging
```

## Quick Commands

```bash
# View staging logs
flyctl logs --app link-content-scraper-staging -f

# Check deployment status
flyctl status --app link-content-scraper-staging

# Open staging app
flyctl open --app link-content-scraper-staging

# SSH into staging machine
flyctl ssh console --app link-content-scraper-staging

# Scale resources (if needed)
flyctl scale memory 2048 --app link-content-scraper-staging
```

## What's Next?

Once staging is working:

1. **Test your features** on mobile/tablet
2. **Share the URL** with teammates for feedback
3. **Iterate quickly** - push changes, auto-deploys in ~2 min
4. **Create PR** when ready for production

## Cost Estimate

**Staging environment costs:**
- **Idle:** $0 (auto-suspends)
- **Active:** ~$0.17/day ($5/month)
- **With regular use:** ~$5-10/month

The auto-suspend feature means you only pay when testing!

## Production Deployment

When you're ready to deploy to production:

```bash
# Manual production deployment
flyctl deploy --config fly.toml --app link-content-scraper

# Or merge to main and create a production deployment workflow
```

## Questions?

See [DEPLOYMENT.md](./DEPLOYMENT.md) for comprehensive documentation.

---

**Happy testing! 🎉**

Your staging environment makes it easy to test the new AI agent features on any device, anywhere!
