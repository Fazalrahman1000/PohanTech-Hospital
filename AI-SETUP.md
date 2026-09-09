# PohanTech local AI agent

This update adds an AI Agent workspace for approved doctors and administrators. Existing clinic features, individual prescription PDFs, and reports remain available. The AI uses **Ollama locally**, with no API key, subscription, Groq, Anthropic, cloud fallback, or external MCP service. Model download needs internet once; local inference runs on your computer.

## 1. Install the update without replacing your database

Stop your Django and React terminals. Back up your existing project and database. Extract `pohantech-ai-update.zip` into your existing `medical-system` folder, merging `backend` and `frontend`. It contains the changed source, new migration, AI guide, and required logo assets. It does **not** contain your database, model weights, virtual environment, or node_modules. Merge your own custom code changes before replacing matching files.

In your existing activated `medical_env`, run from `medical-system`:

```powershell
cd backend
$env:DEBUG='1'
python manage.py migrate
```

Migration `0002` adds AI conversations, proposals, audit events, and content flags. It does not remove or rewrite existing clinical records. No new Python or frontend dependencies are required beyond the previous release.

## 2. Install Ollama and download a model

Download the Windows installer from [Ollama](https://ollama.com/download/windows). Install it, reopen PowerShell, and start the Ollama desktop app.

```powershell
ollama pull qwen3:8b
ollama list
```

`qwen3:8b` is the default general-purpose tool-calling model for this integration. It is not a medically validated model. If loading fails because of memory or it is too slow, use the smaller supported option:

```powershell
ollama pull qwen3:4b
```

The selected model must also match `OLLAMA_MODEL` in the Django environment. `qwen3:14b` is supported for a stronger machine. Larger models require more memory and generally run more slowly on a CPU; no hardware suitability claim is made for your machine.

Keep Ollama bound to its default `127.0.0.1:11434`. Disable Ollama cloud features by setting the Windows user environment variable `OLLAMA_NO_CLOUD=1`, then quit and restart Ollama. Alternatively, quit the desktop app and use a dedicated PowerShell terminal:

```powershell
$env:OLLAMA_NO_CLOUD='1'
$env:OLLAMA_HOST='127.0.0.1:11434'
ollama serve
```

Do not run a second `ollama serve` if the desktop app is already serving that port.

## 3. Start Django and React

In your activated Python environment, from `medical-system/backend`:

```powershell
$env:DEBUG='1'
$env:AI_ENABLED='1'
$env:OLLAMA_BASE_URL='http://127.0.0.1:11434'
$env:OLLAMA_MODEL='qwen3:8b'
python manage.py runserver 127.0.0.1:8000
```

If you downloaded the smaller model, use `$env:OLLAMA_MODEL='qwen3:4b'` instead. Environment values are read at Django startup. `.env.example` is documentation; it is not automatically loaded.

In a second terminal, from `medical-system/frontend`:

```powershell
pnpm dev --port 5174
```

Open http://127.0.0.1:5174 and sign in as a doctor or administrator. Open **AI Agent**. Select Refresh if the model was installed after opening the page. The status should say **Model available**. Staff accounts cannot access the AI UI or its APIs.

## 4. Use the agent

- `Show current drug stock and flag low inventory.`
- `List available doctors and medical services.`
- `Find patient 12 and show their prescription history.`
- `Show revenue for September 2026.`
- `Show revenue from 2026-09-01 to 2026-09-30.`
- `Show revenue for last month.`
- `Prepare a prescription draft for patient 12, doctor 3, diagnosis [doctor-supplied diagnosis], instructions [doctor-supplied instructions], drug batch ID 5, quantity 10, dosage [doctor-supplied dose, frequency and duration].`
- `Draft a payment of 500.00 for patient 12, assigned doctor 3. Note: payment received and awaiting verification.`
- Admin: `Propose restocking drug batch 5 by 20 units. Reason: shipment received.`
- Admin: `Propose marking doctor 3 unavailable. Reason: on leave.`
- Admin: `Review recent community posts for possible spam; propose flags for human review.`

Replace example IDs and bracketed values with real, verified values. The agent must ask for missing clinical parameters and dates. It does not supply autonomous treatment or dosing recommendations. Natural-language date resolution supports English full month names plus year, YYYY-MM, explicit years, this/last month/year, or ISO dates/ranges. Unsupported or ambiguous date requests require clarification. All date filters are inclusive and use the clinic TIME_ZONE. Monthly totals and receipt counts are calculated in Django using decimal amounts and displayed separately as **Verified database totals**, even if the model's prose is inaccurate.

## 5. Review and approve proposals

1. Open **Review queue**. A pending proposal has made no prescription, payment, stock, availability, or post change.
2. Select **Review exact change** and review all payload fields and the inventory snapshot.
3. The designated human checks the confirmation box, then physically clicks **Approve and save** or **Reject proposal**.
4. Prescription approval saves the prescription and dispenses quantities atomically. Stock and expiry are checked again. Payment approval records the positive receipt amount.
5. An approved prescription includes a **Print patient copy** link.

Prescription and payment proposals can be approved only by the selected patient's **currently assigned doctor profile**. An admin who is not that doctor can create a proposal but cannot finalize it; the assigned doctor sees it in their queue. An unassigned patient must be assigned through the clinic workflow before using clinical AI proposals. Ordinary manual workflows retain their existing permissions.

Administrative proposals (restocking, availability, content flags) require the creating admin's review click. Changed stock/availability snapshots fail approval and require a fresh proposal. Review tokens bind the exact payload and reviewer, expire after 15 minutes, and are never sent to the model. Proposals expire after 24 hours and can be finalized only once. No agent tool can call the approval endpoints.

## Privacy and implementation boundaries

- The backend derives access from the authenticated session, then passes a small context of actor ID, admin flag, and doctor profile ID. It never passes passwords, password hashes, emails from login records, session cookies, API keys, or authentication implementation to the model.
- AI doctor queries are limited to patients assigned to that doctor, including their prescriptions and receipts. Admin AI queries cover the clinic. Existing non-AI permissions are unchanged.
- Chat histories belong to their creator. Changes to patient assignment invalidate stored context. **Clear stored chats** deletes your inactive AI conversations, including those from previous page visits; it does not delete clinical records, proposals, approvals, or audit events.
- Chat histories and proposals can contain PHI. They reside in your clinic database; this update does not add field encryption. Protect the database, backups, workstation, and Ollama process. Set organization-specific retention policies. Audit events store action names/outcomes, not prompts or tool arguments.
- The model can call only closed schemas backed by Django ORM functions. No arbitrary SQL, shell, file, URL, plugin, or MCP tools. Unknown tools and extra properties are rejected. Session authentication and CSRF protection apply to AI mutations.
- The adapter permits only loopback HTTP and the supported local Qwen3 tags, disables environment proxies and redirects, and has no cloud fallback. Cloud/provider credentials are not needed or accepted by the AI UI. Keep Ollama cloud disabled as described above.
- Model output is rendered as escaped text and simple Markdown tables. Model-generated HTML, images, and links are not executed or fetched. Prescription PDF links are generated from scoped backend record IDs.
- Tool responses are bounded; searches return at most 20 patients/history entries, 50 drug batches/doctors/services, and 20 recent posts with up to 10 comments each. Search by drug name or patient reference to narrow results. Requests have time/tool limits and per-user throttling.
- There is no validated drug-knowledge database, allergy/interaction checker, RAG medical corpus, or automatic therapeutic substitution. Same-name/type batch suggestions are stock candidates requiring professional verification, not proven equivalents.
- The existing database has availability flags but no appointment schedules, invoices, outstanding balances, or encounter model. The agent reports those limitations rather than fabricating them. Community review is on demand, not an automatic background monitor or compliance certification.

## Verification and troubleshooting

```powershell
# From backend, with your Python environment active:
$env:DEBUG='1'
python manage.py test clinic

# From frontend:
pnpm build
```

Backend tests use mocked model responses to verify permissions, patient scope, conversation ownership, strict schemas, mandatory stock checks, proposal-only behavior, designated-doctor approval, replay prevention, stock rechecking, payment precision, date filters, and refusal of remote/cloud endpoints. The real Ollama model must be downloaded and exercised on your machine; mock tests do not establish model reasoning quality or clinical suitability.

If AI says setup required, run `ollama list`, ensure the tag exactly matches OLLAMA_MODEL, start Ollama, and restart Django after changing environment variables. If requests time out on CPU, use qwen3:4b and narrow the request; OLLAMA_TIMEOUT can be increased in the Django environment. Keep production WSGI/proxy timeouts consistent. If a doctor cannot find a patient, check the patient's assigned doctor. If review expires, refresh the queue and review again. Do not disable permissions or CSRF to resolve errors.

Sources: [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling), [Qwen3 8B](https://ollama.com/library/qwen3:8b), [Ollama local-only configuration](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features).
