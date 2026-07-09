# Security Policy

## Supported versions

Security fixes are applied to the latest release on the `opensource` / `main` branch. Older tags may not receive patches.

## Reporting a vulnerability

**Please do not report security issues through public GitHub/Codeup issues.**

Email the maintainers with:

- Description of the vulnerability and impact
- Steps to reproduce (proof-of-concept if available)
- Affected components (API, Dashboard, SDK, deployment configs)

We aim to acknowledge reports within **5 business days** and will coordinate disclosure after a fix is available.

## Secrets and configuration

- Never commit `.env`, API keys, Supabase keys, or database passwords.
- Use `.env.example` as a template only; rotate any credential that was ever committed to git history.
- In production, keep `USER_TOKEN_SKIP_VALIDATE=false` and configure `USER_TOKEN_REDIS_KEY_TEMPLATE` or `USER_ACCOUNT_VALIDATE_URL`.
- Set a strong `ADMIN_BOOTSTRAP_SECRET` before exposing admin endpoints.

## Hardening checklist

- `APP_DISABLE_AUTH=false` in production
- TLS on Ingress / reverse proxy
- Restrict network access to MySQL, Redis, MongoDB, and Qdrant
- Review CORS settings if exposing the API publicly
