"""Launcher checks: no dependency/model downloads, no clinic database changes.

Run: python -m unittest test_auto -v
"""
import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('clinic_launcher',Path(__file__).with_name('auto.py'))
launcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)

class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='clinic-launcher-test-')
        self.root=Path(self.temp.name)
        self.runtime=self.root/'.runtime';self.runtime.mkdir()
        self.patches=[patch.object(launcher,'ROOT',self.root),patch.object(launcher,'RUNTIME',self.runtime),patch.object(launcher,'STATE',self.runtime/'services.json')]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def test_local_environment_and_custom_ports(self):
        env=launcher.make_env(8012,5182,'qwen3:4b')
        self.assertEqual(env['CLINIC_BACKEND_URL'],'http://127.0.0.1:8012')
        self.assertIn('http://127.0.0.1:5182',env['CSRF_TRUSTED_ORIGINS'])
        self.assertIn('http://localhost:5182',env['CSRF_TRUSTED_ORIGINS'])
        self.assertEqual(env['OLLAMA_NO_CLOUD'],'1')
        self.assertEqual(env['OLLAMA_MODEL'],'qwen3:4b')

    def test_state_cannot_target_another_project(self):
        launcher.STATE.write_text(json.dumps({'root':'another-project','services':{}}))
        with self.assertRaises(launcher.LaunchError):launcher.load_state()

    def test_process_identity_detects_stale_pid_record(self):
        record={'pid':os.getpid(),'identity':'not-the-current-creation-time'}
        self.assertFalse(launcher.owned_alive(record))
        launcher.stop_owned(record)
        self.assertIsNotNone(launcher.process_identity(os.getpid()))

    def test_lock_blocks_second_launcher(self):
        with launcher.launcher_lock():
            with self.assertRaises(launcher.LaunchError):
                with launcher.launcher_lock():pass
        self.assertFalse((self.runtime/'launcher.lock').exists())

    def test_stale_lock_can_be_recovered(self):
        (self.runtime/'launcher.lock').write_text(json.dumps({'pid':os.getpid(),'identity':'stale'}))
        with launcher.launcher_lock():self.assertTrue((self.runtime/'launcher.lock').exists())

    def test_occupied_port_is_not_stopped(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1',0));server.listen(1)
            port=server.getsockname()[1]
            with self.assertRaises(launcher.LaunchError):launcher.require_free(port,'Test')

    def test_real_owned_service_lifecycle(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        services={}
        record=launcher.start_service('test',[sys.executable,'-m','http.server',str(port),'--bind','127.0.0.1'],self.root,os.environ.copy(),services,port)
        try:
            launcher.wait_ready(record,f'http://127.0.0.1:{port}/',10)
            self.assertTrue(launcher.owned_alive(record))
            self.assertEqual(launcher.load_state()['test']['pid'],record['pid'])
        finally:launcher.stop_owned(record)
        self.assertFalse(launcher.owned_alive(record))

    def test_consistent_backup_keeps_original(self):
        (self.root/'backend').mkdir();db=self.root/'backend/db.sqlite3'
        with contextlib.closing(sqlite3.connect(db)) as con:
            con.execute('CREATE TABLE records(value TEXT)');con.execute("INSERT INTO records VALUES ('keep me')");con.commit()
        with patch.dict(os.environ,{'DATABASE_URL':''}):launcher.backup_sqlite()
        backups=list((self.runtime/'backups').glob('*.sqlite3'))
        self.assertEqual(len(backups),1)
        for path in [db,backups[0]]:
            with contextlib.closing(sqlite3.connect(path)) as con:self.assertEqual(con.execute('SELECT value FROM records').fetchone()[0],'keep me')

    def test_missing_manifest_restored_and_pip_repaired(self):
        (self.root/'backend').mkdir()
        python=self.root/'.venv'/('Scripts/python.exe' if launcher.WINDOWS else 'bin/python')
        python.parent.mkdir(parents=True);python.touch()
        with patch.object(launcher,'run') as run,patch.object(launcher.subprocess,'run',return_value=subprocess.CompletedProcess([],1)):
            self.assertEqual(launcher.prepare_python(os.environ.copy()),python)
            commands=[[str(v) for v in c.args[0]] for c in run.call_args_list]
            self.assertIn([str(python),'-m','ensurepip','--upgrade'],commands)
            self.assertTrue(any('install' in c and '-r' in c for c in commands))
        self.assertEqual((self.root/'backend/requirements.txt').read_text(),launcher.REQUIREMENTS)

    def test_stop_preserves_data_and_environment(self):
        for name in ['backend/manage.py','frontend/package.json','backend/db.sqlite3','.venv/keep','models/keep']:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('preserve')
        launcher.save_state({})
        args=argparse.Namespace(reset=False,stop=True,backend_port=8000,frontend_port=5174,model='qwen3:8b',no_browser=True)
        launcher.launch(args)
        for name in ['backend/db.sqlite3','.venv/keep','models/keep']:self.assertEqual((self.root/name).read_text(),'preserve')

    def test_stop_accepts_no_installed_ollama_or_node(self):
        for name in ['backend/manage.py','frontend/package.json']:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.touch()
        with patch.object(launcher.shutil,'which',return_value=None):
            launcher.launch(argparse.Namespace(reset=False,stop=True,backend_port=8000,frontend_port=5174,model='qwen3:8b',no_browser=True))

    def test_supported_port_validation(self):
        self.assertEqual(launcher.port('5174'),5174)
        for value in ['80','65536']:
            with self.assertRaises(argparse.ArgumentTypeError):launcher.port(value)

    def test_reset_runs_setup_without_touching_external_ollama(self):
        for name in ['backend/manage.py','frontend/package.json','backend/db.sqlite3']:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('preserve')
        original={'name':'backend','pid':123,'identity':'test','port':8000}
        launcher.save_state({'backend':original})
        created=[]
        def start(name,command,cwd,env,services,port):
            created.append(name);record={'name':name,'pid':456+len(created),'identity':'test','port':port};services[name]=record;return record
        def get(url):return {'csrfToken':'test'} if '/api/auth/session/' in url else {'models':[{'name':'qwen3:8b'}]}
        with contextlib.ExitStack() as stack:
            stop=stack.enter_context(patch.object(launcher,'stop_owned'))
            stack.enter_context(patch.object(launcher,'require_free'))
            stack.enter_context(patch.object(launcher.shutil,'which',return_value=sys.executable))
            stack.enter_context(patch.object(launcher.subprocess,'check_output',return_value='v22.12.0'))
            stack.enter_context(patch.object(launcher,'find_ollama',return_value='ollama'))
            stack.enter_context(patch.object(launcher,'json_get',side_effect=get))
            stack.enter_context(patch.object(launcher,'prepare_python',return_value=Path(sys.executable)))
            stack.enter_context(patch.object(launcher,'prepare_frontend',return_value=self.root/'vite.js'))
            stack.enter_context(patch.object(launcher,'backup_sqlite'))
            run=stack.enter_context(patch.object(launcher,'run'))
            stack.enter_context(patch.object(launcher,'start_service',side_effect=start))
            stack.enter_context(patch.object(launcher,'wait_ready'))
            launcher.launch(argparse.Namespace(reset=True,stop=False,backend_port=8000,frontend_port=5174,model='qwen3:8b',no_browser=True))
        self.assertEqual(created,['backend','frontend'])
        self.assertEqual([c.args[0] for c in stop.call_args_list if c.args[0] is not None],[original])
        self.assertEqual((self.root/'backend/db.sqlite3').read_text(),'preserve')
        commands=[c.args[0] for c in run.call_args_list]
        self.assertTrue(any('migrate' in c for c in commands))
        self.assertFalse(any('flush' in c or 'seed_demo' in c or 'pull' in c for c in commands))

if __name__=='__main__':unittest.main()
