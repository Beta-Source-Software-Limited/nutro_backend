# Pushti AI — FastAPI + Website (Vercel)

This package is a replacement **example backend folder** built from the existing Pushti AI server source. It preserves the two Android API operations (`/v1/nutrition/resolve` and `/v1/vision/components`) and adds the homepage and privacy policy. It has not been deployed to your account.

## Included

- `main.py`: SQLAlchemy food/alias models, nutrition resolve + optional AI estimates, online plate analysis, website and privacy routes
- `api/index.py`: Vercel entrypoint importing the same `app`
- `site/index.html`, `site/privacy-policy.html`, `site/assets/*`: responsive website (same previously prepared designs)
- `vercel.json`: example rewrites for Vercel Python function
- `init_db.py`: manual creation of tables (not automatically done at server startup)
- `label_aliases.json`: model-label mappings

## URLs after successful deployment

- `GET /`: homepage
- `GET /privacy-policy` and `GET /privacy-policy.html`: privacy policy
- `GET /assets/logo.png`: logo
- `GET /health` or `/api/health`: simple process health check (not a database readiness check)
- `GET /docs`: interactive FastAPI docs
- `POST /v1/nutrition/resolve` or `/api/v1/nutrition/resolve`: nutrition lookup/fallback
- `POST /v1/vision/components` or `/api/v1/vision/components`: optional AI plate analysis

## 1. Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` using your **new** MySQL password; rotate any password that was shared in chat or pushed to GitHub. MySQL passwords containing `@`, `:`, `/`, or `#` need URL encoding in DATABASE_URL. Keep `.env` untracked.

```bash
python init_db.py  # one-time setup on an empty database
uvicorn main:app --reload
```

Test `http://127.0.0.1:8000/`, `/privacy-policy`, `/health`, and `/docs`.

## 2. Vercel

In Vercel, select your existing `pusti-nu` project and verify **Root Directory** points to this backend folder. Set `DATABASE_URL`, `OPENAI_API_KEY` (if needed), and `OPENAI_MODEL` in Project Settings → Environment Variables. Do not upload `.env` into the repo. Use this sample `vercel.json` only if the project is still using `api/index.py` as its function entrypoint; otherwise merge your existing routing rules instead of overwriting them.

Git deployment:
```bash
git add main.py api/index.py site/ label_aliases.json requirements.txt init_db.py vercel.json .gitignore .env.example
git commit -m "Serve Pushti website and preserve nutrition API"
git push origin main
```

Verify after deployment:
```bash
curl -i https://pusti-nu.vercel.app/
curl -i https://pusti-nu.vercel.app/privacy-policy
curl -i https://pusti-nu.vercel.app/health
curl -i -X POST https://pusti-nu.vercel.app/v1/nutrition/resolve \
  -H 'Content-Type: application/json' -d '{"label":"rice"}'
```

For Android, set `NUTRITION_API_BASE_URL` to `https://pusti-nu.vercel.app` for root `/v1/...` URLs. If your app already uses `/api/v1/...`, you may use `https://pusti-nu.vercel.app/api` instead; **don't include both `/api` in the base URL and endpoint path**.

## 3. Important limits

- The nutrition values produced by AI are **estimates**; confirm portion and recipe in the app. This code caches AI estimates under food labels, so recipes with different preparation styles can collide. Extend the cache key before using it for sensitive/critical cases.
- The current website/Privacy Policy includes placeholder support email and other disclosures: replace those before publishing the policy or Google Play listing.
- Vercel route behavior must be tested on the live project; `vercel.json` is not tested against your Vercel account here.
- Protect public AI endpoints with authentication, per-user quotas, and rate limits before production. The vision API accepts JPEG base64 and the 5 MB limit applies to decoded images.
- For production schema updates use migrations (Alembic), not repeated `create_all`.
- The app's `GET /health` shows process health, not MySQL health.
