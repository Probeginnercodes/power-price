# Live demo deployment guide

The hosted backend is prepared for a bounded hiring demo. It has NOT been deployed to AWS. Docker is not installed on this workstation, so image builds, container memory use, the AWS proxy, HTTPS and public-browser behaviour still require validation. Native Python/API/worker tests are separate from container verification.

## Architecture

GitHub Pages serves the dashboard. An HTTPS API receives bounded jobs. SQLite persists anonymous sessions and the queue on one host. A separate worker claims one job, runs the existing research pipeline in a private subprocess/directory, then exposes only that session's permitted outputs. A reviewed historical example is explicitly public. This single-machine design keeps the demo small; it is not a distributed queue or a production trading service.

Anonymous bearer sessions provide job ownership, not verified identity. There is no account signup. Do not publish a static secret in JavaScript. Session tokens live in browser sessionStorage, are sent in Authorization headers, and are hashed in SQLite. Clearing the browser session loses access to its private jobs. Results expire after 24 hours.

## Public limits

- 1–3 evaluation days; 90 or 364 calendar-day training windows.
- One active job per session, at most four queued/running jobs globally.
- Three submissions per client IP per hour; twelve globally per rolling day.
- Twenty anonymous-session handshakes per client IP per hour.
- One worker; 180-second subprocess timeout; interrupted leases become visible failures.
- Server-selected code/data only; no uploads, arbitrary commands, paths or API-key input.
- New job artefacts are isolated under hosted storage; original local research archives are unchanged.

These limits cap work for a small portfolio demo; they do not provide comprehensive anti-abuse protection or an AWS spending cap. Add stronger identity/abuse controls if traffic requires them. A public/shared network may cause visitors to share an IP quota. Model results remain exploratory because forecast vintages are unverified.

## 1. Run without Docker first

From the project folder:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-hosted.txt
python prepare_hosted_seed.py
```

The seed command copies the explicitly reviewed hourly dataset and seven-day historical result. It excludes .env, native archives and other visitors' jobs. Inspect deployment/seed before publication; the package includes only curated inputs, reported outputs and source attribution/provenance hashes.

Terminal A:

```powershell
python -m uvicorn hosted_api:create_app --factory --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Terminal B (activate the same environment):

```powershell
python hosted_worker.py
```

Visit http://127.0.0.1:8000/. Select the public historical example or submit a one-day experiment. Hosted defaults restrict the day input. The original `python serve.py` remains a separate local research interface, without public session/job behaviour.

## 2. Validate Docker locally

Install Docker Desktop with Linux containers/WSL2, then restart the terminal if necessary. The actual image uses Linux Python 3.11 and libgomp for LightGBM. Do not assume native Windows tests prove that image builds.

```powershell
docker version
docker compose config
docker compose up --build
```

Open http://127.0.0.1:8000/. Run a one-day historical job. Check results, sensitivity download, a second browser session's isolation, and a restart. Inspect memory with `docker stats`; time a representative job and confirm the worker stays within its 1200 MB limit before sizing EC2. The API limit is 384 MB; the optional proxy adds up to 128 MB, plus host OS/Docker overhead. Limits are ceilings, not measured usage.

Stop with `docker compose down`. Named volumes retain the queue and results. Do not use `down -v` unless intentionally deleting all hosted state. Volumes on EC2 remain host-local: they are not independent backups and can be lost when the instance/volume is deleted.

## 3. AWS preparation — after Docker passes

1. Confirm the account's current Free-plan eligibility, credit balance and plan expiry in the AWS console. The account display is authoritative; credit expiry and plan duration can differ.
2. Enable MFA and billing notifications. Budget alerts notify; they are not a guaranteed hard spending stop.
3. Select a supported Linux EC2 architecture/size using measured CPU/RAM and the live regional price. Do not assume a micro instance can fit this application or that every instance, disk, address and transfer charge is covered indefinitely.
4. Configure only the required inbound ports: HTTPS 443 and HTTP 80 for certificate provisioning; restrict SSH to your own address. Keep API 8000 loopback-only. Do not add a load balancer or NAT gateway for this small demo.
5. Install Docker on the selected Linux host; transfer the reviewed source and curated seed. Never upload .env, your venv, credentials or original native archives. No ENTSO-E key is required on the public worker.
6. Choose an API DNS hostname you control and point it to the server. GitHub Pages uses HTTPS, so the API must also use valid HTTPS. A domain/DNS service is a separate prerequisite, not supplied by these files.

## 4. Connect HTTPS API and Pages

On the Linux server, set actual values in its shell (examples below are placeholders):

```bash
export API_DOMAIN=api.your-domain.example
export ALLOWED_ORIGINS=https://yourusername.github.io,https://api.your-domain.example
docker compose -f compose.yaml -f deployment/compose.aws.yaml config
docker compose -f compose.yaml -f deployment/compose.aws.yaml up -d --build
```

Caddy handles HTTPS. The proxy has a fixed internal address; only that address is trusted by Uvicorn for forwarded client IPs. This preserves IP quotas without trusting arbitrary internet-supplied forwarded headers. Do not expose API port 8000 publicly. If the fixed private subnet conflicts with an existing network, change the subnet/address and trusted proxy address together.

Use the GitHub origin WITHOUT the repository path. For example, the origin of https://yourusername.github.io/power-project/ is https://yourusername.github.io. If a custom frontend domain is used, add that exact origin instead.

Locally, prepare Pages files:

```powershell
python build_pages.py --api-url https://api.your-domain.example
```

Only pages-dist files belong in the published frontend. The API URL is public configuration, not a secret. Files use repository-relative asset links. Alternatively, enable GitHub Pages with GitHub Actions, then manually run `.github/workflows/pages.yml` with the tested HTTPS API origin. That workflow publishes only the frontend and does not create AWS resources.

## Release checklist

- [ ] Docker image builds and its health endpoint works on Linux.
- [ ] Measured memory/runtime fit the selected EC2 instance with OS overhead.
- [ ] Persistent queue and results survive container recreation; recovery/retention are checked.
- [ ] HTTPS works and exact-origin CORS succeeds from the real GitHub Pages domain.
- [ ] Two real browser sessions cannot access each other's results; downloads work with bearer sessions.
- [ ] Quotas and timeout behaviour are demonstrated in the deployed environment.
- [ ] Billing/credit monitoring is active and backups/cleanup are understood.
- [ ] No secrets/private paths appear in public assets or Docker build context.
- [ ] Research limitations and public-demo restrictions remain visible.

No cloud deployment, credential creation or AWS spending has been performed by the preparation work. A successful native smoke test is not a claim that the unchecked release items have passed.
