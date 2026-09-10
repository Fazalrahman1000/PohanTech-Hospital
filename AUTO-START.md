# Automatic local startup

Place `auto.bat`, `auto.sh`, and **auto.py** in your `medical-system` folder, beside `backend` and `frontend`. The two launchers share auto.py; keep all three files. Install the supplied `frontend/vite.config.js` too, so custom backend ports reach the correct server.

## One-time prerequisites

- Python **3.12+**. On Windows enable **Add Python to PATH** during installation. On Linux install the matching Python venv and pip packages if your distribution separates them.
- Node.js **LTS**, with npm (20.19+ or 22.12+).
- [Ollama](https://ollama.com/download). The launcher starts an installed Ollama if it is not serving, and automatically pulls the chosen model if missing. It does not silently install OS runtimes or request administrator/sudo rights.
- Internet for any missing Python/JavaScript packages and the first model download. Models can require several GB and take significant time to download.

## Windows

From PowerShell inside `medical-system`:

```powershell
.\auto.bat
```

Restart/recheck without deleting records:

```powershell
.\auto.bat --reset
```

## Linux

```bash
chmod +x auto.sh
./auto.sh
./auto.sh --reset
```

Use `bash auto.sh` if you prefer not to change executable permissions.

## What it does

1. Checks prerequisites and port conflicts. It never kills an unrelated server on an occupied port.
2. Creates a project-local `.venv` if needed. It does not change your currently activated `medical_env`.
3. Runs pip against `backend/requirements.txt`, downloading and installing any missing packages, then runs `pip check`. Installed compatible dependencies are reused. If the requirements file is missing, it restores the exact manifest bundled with this release; it does not guess a remote download URL.
4. Installs a project-local pnpm under `.runtime/tools` if needed, installs/checks frontend dependencies from the lockfile, and builds React.
5. Backs up the default SQLite database under `.runtime/backups` before migrations. Runs `manage.py migrate` and `manage.py check`. Backups contain your clinical data; protect this directory. External DATABASE_URL databases require your own backup procedure.
6. Reuses a running local Ollama or starts `ollama serve`. The launcher-started process has cloud features disabled. An existing independently started Ollama retains its own settings.
7. Downloads `qwen3:8b` only if absent. No model is pulled when that exact tag is already installed.
8. Starts Django on **127.0.0.1:8000** and the built React preview on **127.0.0.1:5174**. Checks the backend, frontend, and API proxy before reporting success.
9. Opens your browser. Services continue after the launcher finishes. Logs and process ownership records are kept in `.runtime`.

This launcher is for **local development/use**, with DEBUG=1 and loopback bindings. It is not a production deployment command. The frontend serves its compiled build; source edits appear after `--reset`, not through hot reload. Existing manual `pnpm dev` still works.

## Reset and stop behavior

**`--reset` never deletes the database, patients, prescriptions, accounts, passwords, model downloads, or Python environment.** It stops only the service PIDs recorded by this launcher after verifying their process creation identities, then checks dependencies and starts the services again. It does not run flush, delete db.sqlite3, seed_demo, or reset any passwords.

To stop launcher-owned services:

```powershell
.\auto.bat --stop
```

```bash
./auto.sh --stop
```

An Ollama server started independently (desktop app/system service) is reused and left running. A healthy repeated launch reuses the running clinic. A partial/unhealthy earlier launch asks you to use `--reset`. If startup fails after creating services, it stops the newly created service processes and prints the relevant log path.

## Options

```powershell
.\auto.bat --reset --model qwen3:4b
.\auto.bat --reset --backend-port 8001 --frontend-port 5175
.\auto.bat --no-browser
.\auto.bat --help
```

The same options work with `./auto.sh`. Supported model tags: `qwen3:4b`, `qwen3:8b`, `qwen3:14b`. `OLLAMA_MODEL` is also read as the default model. The launcher sets matching backend, proxy, and local CSRF origin settings for custom ports.

If a port is occupied by a manually started Django/React server, stop that server with Ctrl+C in its original terminal before using the launcher, or choose different ports. `--reset` deliberately does not stop a server whose ownership cannot be verified.

If the application has no accounts, create your own administrator using the launcher's environment:

```powershell
$env:DEBUG='1'
.\.venv\Scripts\python.exe backend\manage.py createsuperuser
```

```bash
DEBUG=1 ./.venv/bin/python backend/manage.py createsuperuser
```

No default credentials are created or changed automatically.

## Verification

Run `python -m unittest test_auto -v` from the project folder to exercise the launcher's checks without downloading packages or model weights. The Windows service lifecycle, process ownership checks, database backup, reset orchestration, dependency repair, and port-conflict handling were tested. Linux uses the same Python implementation through auto.sh, but a live Linux startup was not tested in the delivery environment. A full real-model startup still depends on your installed Ollama and selected model.
