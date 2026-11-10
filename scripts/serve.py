#!/usr/bin/env python3
"""Supervise local API/worker and optional Vite; clean up only owned processes."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
os.environ.setdefault('FRONTEND_DIST', str(root/'frontend/dist'))
commands = [(['uv', 'run', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], root/'backend')]
if os.environ.get('APP_MODE', 'demo') == 'real':
    commands.append((['uv', 'run', 'python', '-m', 'app.cli', 'worker'], root/'backend'))
if '--dev' in sys.argv:
    commands.append((['npm','run','dev'],root/'frontend'))
children=[]
stop=False

def shutdown(_sig=None,_frame=None):
    global stop
    stop=True

signal.signal(signal.SIGINT,shutdown)
signal.signal(signal.SIGTERM,shutdown)
try:
    for cmd,cwd in commands:
        child_env = os.environ.copy()
        if cmd[0] == 'npm':
            for key in list(child_env):
                if key.startswith('GARMIN_') or key in {'DATABASE_URL', 'TEST_DATABASE_URL', 'POSTGRES_PASSWORD'}:
                    child_env.pop(key)
        children.append(subprocess.Popen(cmd,cwd=cwd,env=child_env,start_new_session=True))
    print('Local dashboard: http://127.0.0.1:'+('5173' if '--dev' in sys.argv else '8000'),flush=True)
    while not stop:
        for child in children:
            if child.poll() is not None:
                print(f'A local service exited ({child.returncode}); stopping remaining services.',flush=True)
                stop=True
                break
        time.sleep(0.25)
finally:
    for child in children:
        if child.poll() is None:
            os.killpg(child.pid,signal.SIGTERM)
    for child in children:
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL)
            child.wait()
