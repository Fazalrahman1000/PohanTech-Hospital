"""Shared local launcher for auto.bat / auto.sh. Python standard library only.

--reset means restart launcher-owned services, never reset application data.
"""
import argparse
import contextlib
import ctypes
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / '.runtime'
STATE = RUNTIME / 'services.json'
WINDOWS = os.name == 'nt'
CHILDREN = {}
PNPM_VERSION = '10.33.4'
REQUIREMENTS = '''Django>=5.2,<5.3
djangorestframework>=3.18,<3.19
reportlab>=5,<6
google-auth>=2.40,<3
requests>=2.32,<3
whitenoise>=6.9,<7
dj-database-url>=3,<4
psycopg[binary]>=3.2,<4
'''

class LaunchError(Exception):
    pass

def say(message):
    print(f'[PohanTech] {message}', flush=True)

def process_identity(pid):
    """Creation timestamp distinguishes our process from a later reuse of its PID."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    if WINDOWS:
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                return None
            stamps = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(x) for x in stamps)):
                return None
            return str((stamps[0].dwHighDateTime << 32) | stamps[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        stat = Path(f'/proc/{pid}/stat').read_text()
        fields = stat[stat.rfind(')') + 2:].split()
        if fields[0] == 'Z':
            return None
        return fields[19]  # starttime, field 22; suffix starts at field 3
    except (OSError, IndexError):
        return None

def owned_alive(record):
    return bool(record and record.get('identity') and process_identity(record.get('pid')) == record['identity'])

def stop_owned(record):
    if not owned_alive(record):
        return
    pid = record['pid']
    say(f'Stopping launcher-owned {record.get("name", "service")} (PID {pid}).')
    if WINDOWS:
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        # Recheck before opening; never use taskkill by image or by port.
        if not owned_alive(record):
            return
        handle = kernel.OpenProcess(0x101001, False, pid)  # Query, terminate, synchronize.
        if not handle:
            raise LaunchError(f'Cannot stop PID {pid}; stop it from its original terminal.')
        try:
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            stamps = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(x) for x in stamps)):
                raise LaunchError('Cannot verify process ownership; no process was stopped.')
            created = str((stamps[0].dwHighDateTime << 32) | stamps[0].dwLowDateTime)
            if created != record['identity']:
                return
            if not kernel.TerminateProcess(handle, 0):
                raise LaunchError(f'Cannot stop PID {pid}.')
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            if kernel.WaitForSingleObject(handle, 5000) != 0:
                raise LaunchError(f'PID {pid} is still exiting. Retry in a few seconds.')
        finally:
            kernel.CloseHandle(handle)
    else:
        if hasattr(os,'pidfd_open') and hasattr(signal,'pidfd_send_signal'):
            descriptor=os.pidfd_open(pid)
            try:
                if owned_alive(record): signal.pidfd_send_signal(descriptor,signal.SIGTERM)
            finally: os.close(descriptor)
        elif owned_alive(record):
            os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not owned_alive(record):
            child=CHILDREN.pop(pid,None)
            if child is not None: child.wait(timeout=5)
            return
        time.sleep(.1)
    # Do not escalate to killing an entire process group or unrelated child processes.
    raise LaunchError(f'PID {pid} did not exit. Stop it manually, then retry.')

def load_state():
    if not STATE.exists():
        return {}
    try:
        state = json.loads(STATE.read_text())
        if state.get('root') != str(ROOT):
            raise LaunchError('Launcher state belongs to another project. No processes were stopped.')
        return state.get('services', {})
    except (ValueError, AttributeError) as error:
        raise LaunchError('Invalid .runtime/services.json. No processes were stopped.') from error

def save_state(services):
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps({'root': str(ROOT), 'services': services}, indent=2))
    temporary.replace(STATE)

@contextlib.contextmanager
def launcher_lock():
    RUNTIME.mkdir(exist_ok=True)
    if not RUNTIME.resolve().is_relative_to(ROOT):
        raise LaunchError('.runtime must be inside this project.')
    lock = RUNTIME / 'launcher.lock'
    if lock.exists():
        try:
            previous = json.loads(lock.read_text())
        except (ValueError, OSError):
            raise LaunchError('Invalid launcher lock. Check that no launcher is running before removing .runtime/launcher.lock.')
        if owned_alive(previous):
            raise LaunchError('Another launcher is already running. Wait for it to finish.')
        lock.unlink()
    try:
        with lock.open('x') as handle:
            json.dump({'pid': os.getpid(), 'identity': process_identity(os.getpid())}, handle)
    except FileExistsError:
        raise LaunchError('Another launcher is starting. Retry after it finishes.')
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)

def run(command, cwd=ROOT, env=None):
    result = subprocess.run([str(x) for x in command], cwd=cwd, env=env)
    if result.returncode:
        raise LaunchError(f'{Path(str(command[0])).name} failed (exit {result.returncode}). See the output above.')

def json_get(url):
    # Never forward local requests through system HTTP proxies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=3) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return None

def http_ready(url):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=3) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False

def port_busy(port):
    with socket.socket() as sock:
        sock.settimeout(.3)
        return sock.connect_ex(('127.0.0.1', port)) == 0

def require_free(port, name):
    if port_busy(port):
        raise LaunchError(f'{name} port {port} is occupied by a server not managed by this launcher. Stop that server in its terminal or choose a different port. --reset never kills unrelated servers.')

def start_service(name, command, cwd, env, services, port):
    log_path = RUNTIME / f'{name}.log'
    options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {'start_new_session': True}
    with log_path.open('ab', buffering=0) as log:
        process = subprocess.Popen([str(x) for x in command], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, **options)
    CHILDREN[process.pid] = process
    identity = process_identity(process.pid)
    if identity is None:
        process.poll()
        raise LaunchError(f'{name} exited immediately. Read {log_path}.')
    record = {'name': name, 'pid': process.pid, 'identity': identity, 'port': port}
    services[name] = record
    save_state(services)
    return record

def wait_ready(record, url, timeout=40):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if not owned_alive(record):
            raise LaunchError(f'{record["name"]} exited. Read .runtime/{record["name"]}.log.')
        if http_ready(url):
            return
        time.sleep(.5)
    raise LaunchError(f'{record["name"]} is not ready. Read .runtime/{record["name"]}.log.')

def find_ollama():
    exe = shutil.which('ollama')
    if not exe and WINDOWS:
        candidate = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Ollama/ollama.exe'
        if candidate.is_file():
            exe = str(candidate)
    return exe

def npm_command(node):
    npm = shutil.which('npm')
    if npm and not WINDOWS:
        return [npm]
    candidates = [Path(node).resolve().parent / 'node_modules/npm/bin/npm-cli.js']
    if npm:
        candidates += [Path(npm).parent / 'node_modules/npm/bin/npm-cli.js', Path(npm).resolve().parent / 'npm-cli.js']
    for candidate in candidates:
        if candidate.is_file():
            return [node, str(candidate)]
    raise LaunchError('npm is missing. Install Node.js LTS with npm and reopen the terminal.')

def prepare_python(env):
    requirements = ROOT / 'backend/requirements.txt'
    if not requirements.exists():
        say('Restoring the bundled requirements.txt manifest.')
        requirements.write_text(REQUIREMENTS)
    venv = ROOT / '.venv'
    python = venv / ('Scripts/python.exe' if WINDOWS else 'bin/python')
    if not python.exists():
        say('Creating the project-local .venv environment.')
        run([sys.executable, '-m', 'venv', venv], env=env)
    probe = subprocess.run([str(python), '-m', 'pip', '--version'], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode:
        say('Repairing pip in the project environment.')
        run([python, '-m', 'ensurepip', '--upgrade'], env=env)
    say('Checking Python requirements; downloading/installing missing dependencies.')
    run([python, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', requirements], env=env)
    run([python, '-m', 'pip', 'check'], env=env)
    return python

def prepare_frontend(node, env):
    # Install pnpm locally, not globally; do not depend on user shell profiles.
    tools = RUNTIME / 'tools'
    bin_dir = tools / 'node_modules/pnpm/bin'
    entry = next((p for p in [bin_dir / 'pnpm.cjs', bin_dir / 'pnpm.mjs'] if p.exists()), None)
    if entry is None:
        say('Installing the project-local pnpm package manager.')
        run(npm_command(node) + ['install', '--prefix', str(tools), '--no-save', '--ignore-scripts', '--no-audit', '--no-fund', f'pnpm@{PNPM_VERSION}'], env=env)
        entry = next((p for p in [bin_dir / 'pnpm.cjs', bin_dir / 'pnpm.mjs'] if p.exists()), None)
        if entry is None:
            raise LaunchError('The local pnpm installation is incomplete.')
    frontend = ROOT / 'frontend'
    say('Checking/installing frontend dependencies.')
    command = [node, entry, 'install']
    if (frontend / 'pnpm-lock.yaml').exists():
        command += ['--frozen-lockfile']
    run(command, cwd=frontend, env=env)
    say('Building React for the local preview server.')
    run([node, entry, 'run', 'build'], cwd=frontend, env=env)
    return frontend / 'node_modules/vite/bin/vite.js'

def backup_sqlite():
    # Online backup API produces a consistent snapshot; never remove the source.
    db = ROOT / 'backend/db.sqlite3'
    if db.exists() and not os.environ.get('DATABASE_URL'):
        backup = RUNTIME / 'backups'
        backup.mkdir(exist_ok=True)
        target = backup / f'before-start-{time.time_ns()}.sqlite3'
        with contextlib.closing(sqlite3.connect(db)) as source, contextlib.closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
        say(f'Database backed up to {target.relative_to(ROOT)}.')

def make_env(backend_port, frontend_port, model):
    env = os.environ.copy()
    env.update({'DEBUG': '1', 'PYTHONUNBUFFERED': '1', 'AI_ENABLED': '1', 'OLLAMA_MODEL': model,
        'OLLAMA_BASE_URL': 'http://127.0.0.1:11434', 'OLLAMA_HOST': '127.0.0.1:11434', 'OLLAMA_NO_CLOUD': '1',
        'CLINIC_BACKEND_URL': f'http://127.0.0.1:{backend_port}'})
    origins = [x.strip() for x in env.get('CSRF_TRUSTED_ORIGINS', '').split(',') if x.strip()]
    origins += [f'http://{host}:{frontend_port}' for host in ('127.0.0.1','localhost')]
    env['CSRF_TRUSTED_ORIGINS'] = ','.join(dict.fromkeys(origins))
    hosts = [x.strip() for x in env.get('ALLOWED_HOSTS','').split(',') if x.strip()]
    env['ALLOWED_HOSTS'] = ','.join(dict.fromkeys(hosts + ['127.0.0.1','localhost']))
    env['CI']='1'  # Dependency installation must not wait for interactive prompts.
    return env

def launch(args):
    if sys.version_info < (3, 12):
        raise LaunchError('Use Python 3.12 or newer.')
    if not (ROOT / 'backend/manage.py').is_file() or not (ROOT / 'frontend/package.json').is_file():
        raise LaunchError('Place auto.bat, auto.sh and auto.py in medical-system, beside backend and frontend.')
    if args.backend_port == args.frontend_port or 11434 in (args.backend_port, args.frontend_port):
        raise LaunchError('Backend, frontend and Ollama require separate ports.')
    with launcher_lock():
        services = load_state()
        if args.reset or args.stop:
            for name in ('frontend','backend','ollama'):
                stop_owned(services.get(name))
                services.pop(name, None)
                save_state(services)
            say('Managed services stopped. Database, accounts, models, and environments are preserved.')
            if args.stop:
                return
        active = {k:v for k,v in services.items() if owned_alive(v)}
        services = active
        if 'backend' in active or 'frontend' in active:
            if all(k in active for k in ('backend','frontend')) and active['backend']['port'] == args.backend_port and active['frontend']['port'] == args.frontend_port:
                tags=json_get('http://127.0.0.1:11434/api/tags')
                model_ready=isinstance(tags,dict) and args.model in {m.get('name') for m in tags.get('models',[])}
                if model_ready and active['backend'].get('model')==args.model and http_ready(f'http://127.0.0.1:{args.backend_port}/api/auth/session/') and http_ready(f'http://127.0.0.1:{args.frontend_port}/'):
                    say(f'Already running: http://127.0.0.1:{args.frontend_port}/ . Use --reset to restart or change the model.')
                    return
            raise LaunchError('An earlier managed launch needs restarting (service/model/ports changed). Run with --reset to repair it.')
        require_free(args.backend_port, 'Django')
        require_free(args.frontend_port, 'React')
        node = shutil.which('node')
        if not node:
            raise LaunchError('Install Node.js LTS (20.19+ or 22.12+) and npm, then reopen your terminal.')
        version = subprocess.check_output([node, '--version'], text=True).strip().lstrip('v')
        numbers = tuple(map(int, version.split('.')[:2]))
        if numbers < (20,19) or numbers[0] == 21 or numbers[0] == 22 and numbers < (22,12):
            raise LaunchError('Node.js is too old. Install current Node.js LTS.')
        ollama = find_ollama()
        tags = json_get('http://127.0.0.1:11434/api/tags')
        installed = {m.get('name') for m in tags.get('models',[])} if isinstance(tags,dict) else set()
        if not ollama and (not isinstance(tags,dict) or args.model not in installed):
            raise LaunchError('Install Ollama first from https://ollama.com/download . Reopen your terminal. This launcher will then start it and download the selected model automatically.')
        env = make_env(args.backend_port,args.frontend_port,args.model)
        env['PATH'] = str(Path(node).parent) + os.pathsep + env.get('PATH','')
        started = []
        try:
            python = prepare_python(env)
            vite = prepare_frontend(node, env)
            backup_sqlite()
            say('Applying pending Django migrations (no database reset).')
            run([python, 'manage.py', 'migrate', '--noinput'], cwd=ROOT/'backend', env=env)
            run([python, 'manage.py', 'check'], cwd=ROOT/'backend', env=env)
            # Setup may take several minutes. Recheck in case the desktop app
            # was started while dependencies were being installed.
            tags = json_get('http://127.0.0.1:11434/api/tags')
            installed = {m.get('name') for m in tags.get('models',[])} if isinstance(tags,dict) else set()
            if not isinstance(tags,dict):
                require_free(11434, 'Ollama')
                say('Starting Ollama locally.')
                record = start_service('ollama',[ollama,'serve'],ROOT,env,services,11434)
                started.append('ollama')
                wait_ready(record,'http://127.0.0.1:11434/api/tags',60)
            else:
                say('Reusing the already-running Ollama server; it will not be stopped unless this launcher owns it.')
            if args.model not in installed:
                say(f'Downloading {args.model}. This may take time and several GB of disk space.')
                run([ollama, 'pull', args.model], env=env)
            latest = json_get('http://127.0.0.1:11434/api/tags')
            if not isinstance(latest,dict) or args.model not in {m.get('name') for m in latest.get('models',[])}:
                raise LaunchError('The configured Ollama model is not available after setup.')
            # Recheck ports in case another application started during installation.
            require_free(args.backend_port,'Django'); require_free(args.frontend_port,'React')
            record = start_service('backend',[python,'manage.py','runserver',f'127.0.0.1:{args.backend_port}','--noreload'],ROOT/'backend',env,services,args.backend_port)
            started.append('backend')
            record['model']=args.model
            save_state(services)
            wait_ready(record,f'http://127.0.0.1:{args.backend_port}/api/auth/session/')
            record = start_service('frontend',[node,vite,'preview','--host','127.0.0.1','--port',str(args.frontend_port),'--strictPort','--configLoader','native'],ROOT/'frontend',env,services,args.frontend_port)
            started.append('frontend')
            wait_ready(record,f'http://127.0.0.1:{args.frontend_port}/')
            proxied = json_get(f'http://127.0.0.1:{args.frontend_port}/api/auth/session/')
            if not isinstance(proxied,dict) or 'csrfToken' not in proxied:
                raise LaunchError('Frontend API proxy check failed. Install the supplied vite.config.js and retry.')
        except BaseException:
            for name in reversed(started):
                try:
                    stop_owned(services.get(name))
                    services.pop(name,None)
                except LaunchError as error:
                    say(str(error))
            save_state(services)
            raise
        save_state(services)
        say(f'Ready: http://127.0.0.1:{args.frontend_port}/')
        say('Logs: .runtime/backend.log, frontend.log and ollama.log. Close this terminal if desired; services continue running.')
        say('Use --stop to stop managed services, or --reset to restart. Existing passwords are unchanged.')
        if not args.no_browser:
            webbrowser.open(f'http://127.0.0.1:{args.frontend_port}/')

def port(value):
    value = int(value)
    if not 1024 <= value <= 65535:
        raise argparse.ArgumentTypeError('Use a port from 1024 to 65535.')
    return value

def main():
    parser = argparse.ArgumentParser(description='Start the local PohanTech clinic and Ollama. Reset never deletes data.')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--reset',action='store_true',help='Restart only launcher-owned services and recheck dependencies; preserve data.')
    modes.add_argument('--stop',action='store_true',help='Stop only launcher-owned services.')
    parser.add_argument('--model',choices=['qwen3:4b','qwen3:8b','qwen3:14b'],default=os.getenv('OLLAMA_MODEL','qwen3:8b'))
    parser.add_argument('--backend-port',type=port,default=8000)
    parser.add_argument('--frontend-port',type=port,default=5174)
    parser.add_argument('--no-browser',action='store_true')
    args = parser.parse_args()
    if args.model not in ('qwen3:4b','qwen3:8b','qwen3:14b'):
        parser.error('OLLAMA_MODEL must be a supported local qwen3 tag.')
    try:
        launch(args)
    except KeyboardInterrupt:
        say('Setup cancelled. Newly started services have been cleaned up.')
        return 130
    except (LaunchError,OSError,subprocess.SubprocessError) as error:
        say(f'ERROR: {error}')
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
