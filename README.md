# Medora — Django + React clinic management

A working local application with an animated login/register interface, session authentication, administrator-approved registration, verified Google ID-token sign-in, clinic dashboards, doctor profiles, patients, prescriptions, pharmacy batches, payments, team posts, comments, likes, and monthly/yearly PDF reports.

## Run locally

Requires Python 3.12+ and Node.js 20.19+ with pnpm. Run commands from this folder. Use two terminals.

### Django (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements.txt
$env:DEBUG='1'
cd backend
..\.venv\Scripts\python manage.py migrate
..\.venv\Scripts\python manage.py createsuperuser
..\.venv\Scripts\python manage.py runserver 127.0.0.1:8000
```

For `createsuperuser`, use the **same email address for username and email**. Superusers can access the app without approval. Environment variables must be set in the shell or deployment configuration; `.env.example` is a reference and is not automatically loaded.

### React (second terminal)

```powershell
cd frontend
pnpm install
pnpm dev
```

Open http://127.0.0.1:5173. Vite forwards `/api` and `/admin` to Django. No clinical data is stored in browser localStorage.

### Local login troubleshooting

With `DEBUG=1`, Django accepts local frontend origins on ports 5173 and 5174 for both localhost and 127.0.0.1. Restart Django after changing settings and reload the login page to get a fresh CSRF token. Production origins must be explicitly configured in CSRF_TRUSTED_ORIGINS.

Vite now uses port 5173 with strictPort enabled: it reports an occupied port instead of silently moving to 5174. Stop your previous frontend server before starting another, or explicitly run `pnpm dev --port 5174`. The React DevTools console message is informational and does not prevent login.

### Optional fictional demo

In the Django terminal, before running the server:

```powershell
$env:DEMO_PASSWORD='Choose-a-strong-local-password'
..\.venv\Scripts\python manage.py seed_demo
```

Sign in as `admin@medora.local` with that password. The command only works with DEBUG=1, creates entirely fictional records, and does not overwrite an existing demo. Never seed a clinical database.

## Workflows

- Admin: create medical services and doctor accounts; approve staff registrations in Accounts; add drug batches and restock; all clinical workflows.
- Doctor: view their profile in Doctors; register patients; prescribe using their own doctor identity; access clinic records and reports.
- Staff: register patients, record payments, read records, and participate in the team feed. Cannot prescribe, add doctors, or change stock.
- Prescription Save immediately dispenses the entered quantities. All items validate first; expired batches, duplicate lines, and insufficient quantities are rejected. Transactional updates create an immutable stock ledger alongside the prescription. There is no draft/dispensing separation or automatic dose calculation.
- Inventory is per batch, with manufacture, arrival, and expiry dates. Add a new batch for a new expiry date; Restock adds units to an existing unexpired batch.
- Payments are positive decimal receipts, never floating-point calculations. All amounts use one unspecified clinic currency; choose and document your currency before operational use.
- Patient registration timestamps are automatic. A patient ID card is unique; OPD/IPD/Emergency/Other categorizes the initial registration. Prescriptions can be added repeatedly. Separate repeat-visit/encounter management is not implemented.
- Dashboard shows current week, month, year, available doctors, services, and selected-period receipts. Reports lets you select historical monthly/yearly periods.
- PDFs include clinic/payment summaries, prescription logs, or current drug inventory with period-filtered stock movements. Historical inventory balance snapshots are not implemented.
- Clinical and financial records are append-only in this version. Corrections, refunds, prescription cancellation/reversal, and deletion need dedicated audited workflows before operational use.

## Google sign-in

Create a Google OAuth Web client. Add `http://127.0.0.1:5173` as an authorized JavaScript origin (and your HTTPS origin for deployment). Set `GOOGLE_CLIENT_ID` in the Django environment and restart it. The frontend loads Google Identity Services only when configured. The server verifies signature, audience, expiry, and verified email using Google's library. New Google users require administrator approval. Existing password accounts are not automatically linked by email.

Reference: https://developers.google.com/identity/gsi/web/guides/verify-google-id-token

## Checks

```powershell
cd backend
..\.venv\Scripts\python manage.py test clinic
cd ../frontend
pnpm build
```

Tests cover dispensing, multi-item rollback, expiration, duplicate drug lines, role restrictions, pending accounts, decimal payments, reporting periods, restocking, PDF responses, likes/comments, CSRF login, and registration privilege protection.

## Deployment and limits

This delivery is a local working application, not a deployed or certified clinical system. Use PostgreSQL via DATABASE_URL for production. Build React with `pnpm build`; serve `frontend/dist` through a web server and forward `/api/` and `/admin/` to a production WSGI server using `config.wsgi:application`. Run migrations and collectstatic. Set a strong SECRET_KEY, DEBUG=0, exact ALLOWED_HOSTS, HTTPS CSRF_TRUSTED_ORIGINS, and your clinic TIME_ZONE. HTTPS and secure cookies are enabled when DEBUG=0. Configure proxy HTTPS detection carefully if terminating TLS upstream.

Before real patient use, complete organization-specific access/privacy review, backups and restore testing, deployment monitoring, identity recovery and verification, MFA requirements, patient-record read-access auditing, account lifecycle management, and load/concurrency testing against PostgreSQL. This version grants approved clinic staff shared record visibility; it does not implement tenant isolation or patient assignment-based access. Anonymous throttling uses Django's default cache; configure shared persistent throttling for a multi-worker deployment.

Source layout: `backend/clinic` contains the domain/API/tests; `frontend/src` contains the React UI. `backend/clinic/migrations` contains the initial database migration.
