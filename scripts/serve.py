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
private = root / 'private'
mode = os.environ.get('APP_MODE', 'demo')
if mode not in {'test', 'demo', 'real'}:
    raise SystemExit('APP_MODE must be test, demo or real.')
native = mode != 'real' or os.environ.get('GOING_BANANAS_BACKEND') == 'go'
os.environ.setdefault('APP_MODE', mode)
bin_dir = private / 'bin'

def build_backend():
    if native:
        bin_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        env = os.environ.copy()
        env['PATH'] = str(private/'go-tools'/'bin') + os.pathsep + env.get('PATH', '')
        env.setdefault('GOPATH', str(private/'cache'/'go'))
        env.setdefault('GOCACHE', str(private/'cache'/'go-build'))
        subprocess.run(['go', 'build', '-o', str(bin_dir) + '/',
                        './cmd/going-bananas', './cmd/garmin-worker'], cwd=root/'backend-go', env=env, check=True)

if sys.argv[1:] == ['--build']:
    build_backend()
    raise SystemExit(0)
if sys.argv[1:] not in ([], ['--dev']):
    raise SystemExit('Usage: serve.py [--dev | --build]')
dev = sys.argv[1:] == ['--dev']

def port(key, default):
    value = os.environ.get(key, str(default))
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 65535:
        raise SystemExit(f'{key} must be an integer from 1 to 65535.')
    return int(value)

api_port = port('APP_PORT', 8000)
vite_port = port('VITE_PORT', 5173)
if dev and api_port == vite_port:
    raise SystemExit('VITE_PORT and APP_PORT must be distinct.')
# Finder, launchd, and make share this hold for the life of the supervisor.
private.mkdir(mode=0o700, exist_ok=True)
lock = (private / 'dashboard-serve.lock').open('a')
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('Going Bananas is already starting or running from this checkout.')
for requested in ([api_port, vite_port] if dev else [api_port]):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(('127.0.0.1', requested))
        except OSError:
            raise SystemExit(f'Port {requested} is already occupied. Stop the other service before starting Going Bananas.')

os.environ.setdefault('FRONTEND_DIST', str(root/'frontend/dist'))
if native:
    build_backend()
    commands = [([str(bin_dir/'going-bananas'), 'serve', '-startup', '-repo', str(root),
                  '-listen', f'127.0.0.1:{api_port}'], root)]
    if mode == 'real':
        commands.append(([str(bin_dir/'garmin-worker'), 'worker'], root))
else:
    commands = [(['uv', 'run', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(api_port)], root/'backend'),
                (['uv', 'run', 'python', '-m', 'app.cli', 'worker'], root/'backend')]
    startup = subprocess.run(['uv', 'run', 'python', '-m', 'app.cli', 'metrics-refresh-today'], cwd=root/'backend')
    if startup.returncode != 0:
        print('Startup metric refresh failed; metric pages compute on view until the next write.', flush=True)
if dev:
    commands.append((['npm','run','dev','--','--port',str(vite_port),'--strictPort'],root/'frontend'))
children=[]
stop=False
exit_code=0

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
    print('Local dashboard: http://127.0.0.1:'+str(vite_port if dev else api_port),flush=True)
    while not stop:
        for child in children:
            if child.poll() is not None:
                exit_code = child.returncode or 1
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

raise SystemExit(exit_code)
