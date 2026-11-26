#!/usr/bin/env python3
"""Supervise local API/worker and optional Vite; clean up only owned processes."""
import fcntl
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
# Finder, launchd, and make share this hold for the life of the supervisor.
private = root / 'private'
private.mkdir(mode=0o700, exist_ok=True)
lock = (private / 'dashboard-serve.lock').open('a')
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('Going Bananas is already starting or running from this checkout.')
with socket.socket() as listener:
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(('127.0.0.1', 8000))
    except OSError:
        raise SystemExit('Port 8000 is already occupied. Stop the other service before starting Going Bananas.')
os.environ.setdefault('FRONTEND_DIST', str(root/'frontend/dist'))
commands = [(['uv', 'run', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], root/'backend')]
if os.environ.get('APP_MODE', 'demo') == 'real':
    commands.append((['uv', 'run', 'python', '-m', 'app.cli', 'worker'], root/'backend'))
if '--dev' in sys.argv:
    commands.append((['npm','run','dev'],root/'frontend'))
startup = subprocess.run(['uv', 'run', 'python', '-m', 'app.cli', 'metrics-refresh-today'], cwd=root/'backend')
if startup.returncode != 0:
    print('Startup metric refresh failed; metric pages compute on view until the next write.', flush=True)
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
