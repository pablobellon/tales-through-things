"""Tales Through Things (T3) — server for the iPad installation.

usage (from the project folder):  python3 server/main.py

Serves web/ over HTTPS (needed for the iPad microphone) and the API:

  GET  /api/collection                      the archived memories
  POST /api/yesno?q=invite|archive  (wav)   understand a spoken yes / not yet
  POST /api/session                         start: random theme, first question
  POST /api/session/<id>/answer     (wav)   next question, or {done} → generation starts
  GET  /api/session/<id>                    generation status / the finished memory
  POST /api/session/<id>/finish     (json)  {"keep": true|false} → archive or delete

Certificates: same local CA as the demo (certs/), so a trusted iPad needs no setup.
"""
import hashlib
import hmac
import http.server
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import traceback
from functools import partial
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)


def load_env():
    """Minimal .env reader (KEY=value lines), so API keys stay out of the code."""
    path = os.path.join(ROOT, '.env')
    if os.path.isfile(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()  # before the modules that read settings at import time

import archive  # noqa: E402
from providers import load_providers  # noqa: E402
from sessions import SCRIPT, Sessions  # noqa: E402

WEB = os.path.join(ROOT, 'web')
CERTS = os.path.join(ROOT, 'certs')
PORT = int(os.environ.get('T3_PORT', 8444))
# On a server behind a web proxy that does HTTPS (Caddy...): plain HTTP on localhost.
BEHIND_PROXY = os.environ.get('T3_BEHIND_PROXY') == '1'
# Optional passcode screen (remote testing): only people with the code can use it.
PASSCODE = os.environ.get('T3_PASSCODE', '').strip()
PASS_COOKIE = 't3pass'



def _server_secret():
    """Random secret kept next to the data (never in the code): signs the login cookie."""
    path = os.path.join(archive.DATA, '.t3-secret')
    if not os.path.isfile(path):
        os.makedirs(archive.DATA, exist_ok=True)
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
            f.write(os.urandom(32))
    return open(path, 'rb').read()


PASS_TOKEN = (hmac.new(_server_secret(), PASSCODE.encode(), hashlib.sha256).hexdigest()
              if PASSCODE else '')

# Guessing protection: failed logins per visitor and overall (sliding windows).
LOGIN_FAILS_PER_IP = 8          # per 15 minutes
LOGIN_FAILS_TOTAL = 40          # per hour, all visitors together → logins paused
_fails = {}                     # ip -> [timestamps]
_fails_lock = threading.Lock()


def _too_many_failures(ip):
    now = time.time()
    with _fails_lock:
        recent_all = [t for ts in _fails.values() for t in ts if now - t < 3600]
        mine = [t for t in _fails.get(ip, []) if now - t < 900]
        return len(mine) >= LOGIN_FAILS_PER_IP or len(recent_all) >= LOGIN_FAILS_TOTAL


def _record_failure(ip):
    now = time.time()
    with _fails_lock:
        _fails[ip] = [t for t in _fails.get(ip, []) if now - t < 3600] + [now]
        for k in [k for k, ts in _fails.items() if not ts or now - ts[-1] > 3600]:
            del _fails[k]

LOGIN_PAGE = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tales Through Things</title>
<style>
  @font-face { font-family: Lexend; src: url(fonts/lexend-latin.woff2) format('woff2'); }
  html, body { height: 100%; margin: 0; background: #E3963E; font-family: Lexend, system-ui, sans-serif; }
  body { display: flex; align-items: center; justify-content: center; }
  form { width: min(80vmin, 420px); aspect-ratio: 1; border-radius: 50%; background: #000; color: #fff;
         display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 18px; }
  h1 { font-weight: 500; font-size: 22px; margin: 0; text-align: center; line-height: 1.3; }
  input { font: inherit; font-size: 18px; width: 60%; padding: 10px 14px; border-radius: 30px; border: 0; text-align: center; }
  button { font: inherit; font-size: 16px; padding: 9px 26px; border-radius: 30px; border: 0; background: #5F5DFF; color: #fff; }
  p { color: #ff9b9b; margin: 0; font-size: 14px; min-height: 1em; }
</style></head><body>
<form method="post" action="/login">
  <h1>Tales Through Things</h1>
  <input name="passcode" type="password" placeholder="Passcode" autofocus autocomplete="current-password">
  <button type="submit">Enter</button>
  <p>{message}</p>
</form></body></html>'''


# ------------------------------------------------------------------ certificates

def local_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    for iface in ('en0', 'en1', 'bridge100'):
        out = subprocess.run(['ipconfig', 'getifaddr', iface], capture_output=True, text=True).stdout.strip()
        if out:
            ips.add(out)
    return sorted(ips)


def local_hostname():
    out = subprocess.run(['scutil', '--get', 'LocalHostName'], capture_output=True, text=True).stdout.strip()
    return f'{out}.local' if out else None


def make_server_cert(ips, hostname):
    """Re-made on every start so it matches the current IP. Signed by certs/rootCA."""
    ca_key, ca_crt = os.path.join(CERTS, 'rootCA.key'), os.path.join(CERTS, 'rootCA.crt')
    key, crt = os.path.join(CERTS, 'server.key'), os.path.join(CERTS, 'server.crt')
    csr, ext = os.path.join(CERTS, 'server.csr'), os.path.join(CERTS, 'server.ext')
    if not os.path.exists(ca_crt):
        sys.exit('certs/rootCA.crt missing: copy certs/ from sequence_fake_video (the CA the iPad trusts).')
    names = ['DNS:localhost'] + ([f'DNS:{hostname}'] if hostname else []) + \
            [f'IP:{ip}' for ip in ['127.0.0.1', *ips]]
    with open(ext, 'w') as f:
        f.write('basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n'
                f'extendedKeyUsage=serverAuth\nsubjectAltName={",".join(names)}\n')
    run = lambda *a: subprocess.run(a, check=True, capture_output=True)  # noqa: E731
    run('openssl', 'genrsa', '-out', key, '2048')
    run('openssl', 'req', '-new', '-key', key, '-subj', '/CN=Tales Through Things', '-out', csr)
    run('openssl', 'x509', '-req', '-in', csr, '-CA', ca_crt, '-CAkey', ca_key, '-CAcreateserial',
        '-out', crt, '-days', '800', '-sha256', '-extfile', ext)
    return key, crt


# ------------------------------------------------------------------ live reload

def site_version():
    latest = 0
    for dirpath, _, filenames in os.walk(WEB):
        for name in filenames:
            try:
                latest = max(latest, os.stat(os.path.join(dirpath, name)).st_mtime)
            except OSError:
                pass
    return latest


# ------------------------------------------------------------------ HTTP

SESSION_RE = re.compile(r'^/api/session/([0-9a-f]{12})(/answer|/finish)?$')
FILE_RE = re.compile(r'^/(archive|runs)/([\w-]{1,64})/(points\.bin|meta\.json)$')


class Handler(http.server.SimpleHTTPRequestHandler):
    sessions = None  # set in main()

    # -- responses

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > 20 * 1024 * 1024:
            raise ValueError('upload too large')
        return self.rfile.read(n) if n else b''

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def _client_ip(self):
        if BEHIND_PROXY:  # Caddy puts the visitor's address last
            fwd = self.headers.get('X-Forwarded-For', '')
            if fwd:
                return fwd.split(',')[-1].strip()
        return self.client_address[0]

    def log_message(self, fmt, *args):
        if self.path.startswith('/api/'):
            sys.stderr.write('%s %s\n' % (self.command, self.path))

    # -- passcode

    def _allowed(self):
        if not PASSCODE:
            return True
        cookie = SimpleCookie(self.headers.get('Cookie', ''))
        return PASS_COOKIE in cookie and hmac.compare_digest(cookie[PASS_COOKIE].value, PASS_TOKEN)

    def _login_page(self, message='', status=200):
        body = LOGIN_PAGE.replace('{message}', message).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _gate(self, path):
        """True if the request may go on; otherwise answers with the login page / 401."""
        if self._allowed() or path.startswith('/fonts/'):
            return True
        if path.startswith('/api/') or path == '/__version':
            self._json({'error': 'passcode required'}, 401)
        else:
            self._login_page()
        return False

    def _login(self):
        ip = self._client_ip()
        if _too_many_failures(ip):
            return self._login_page('Too many attempts. Please try again later.', 429)
        form = parse_qs(self._body().decode('utf-8', 'replace'))
        given = form.get('passcode', [''])[0].strip()
        if not hmac.compare_digest(given.encode(), PASSCODE.encode()):
            _record_failure(ip)
            print(f'failed login from {ip}', flush=True)
            return self._login_page('Wrong passcode', 403)
        self.send_response(303)
        secure = '; Secure' if BEHIND_PROXY else ''
        self.send_header('Set-Cookie', f'{PASS_COOKIE}={PASS_TOKEN}; Path=/; Max-Age=2592000; '
                                       f'HttpOnly; SameSite=Lax{secure}')
        self.send_header('Location', '/')
        self.end_headers()

    # -- routes

    def do_GET(self):
        path = urlparse(self.path).path
        if not self._gate(path):
            return
        try:
            if path == '/__version':
                return self._json(site_version())
            if path == '/api/collection':
                return self._json(archive.list_memories())
            if path == '/api/script':
                return self._json(SCRIPT['lines'])
            m = SESSION_RE.match(path)
            if m and not m.group(2):
                return self._json(self.sessions.status(m.group(1)))
            m = FILE_RE.match(path)
            if m:
                base = archive.ARCHIVE if m.group(1) == 'archive' else archive.RUNS
                return self._file(os.path.join(base, m.group(2), m.group(3)))
            if path.startswith('/api/'):
                return self._json({'error': 'not found'}, 404)
        except KeyError as err:
            return self._json({'error': str(err)}, 404)
        # everything else: static files from web/ only
        super().do_GET()

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path
        if path == '/login' and PASSCODE:
            return self._login()
        if not self._gate(path):
            return
        try:
            if path == '/api/yesno':
                q = parse_qs(url.query).get('q', ['invite'])[0]
                return self._json(self.sessions.transcribe_yes_no(q, self._body()))
            if path == '/api/session':
                return self._json(self.sessions.start())
            m = SESSION_RE.match(path)
            if m and m.group(2) == '/answer':
                return self._json(self.sessions.answer(m.group(1), self._body()))
            if m and m.group(2) == '/finish':
                keep = bool(json.loads(self._body() or b'{}').get('keep'))
                return self._json(self.sessions.finish(m.group(1), keep))
            return self._json({'error': 'not found'}, 404)
        except KeyError as err:
            return self._json({'error': str(err)}, 404)
        except Exception as err:
            traceback.print_exc()
            return self._json({'error': repr(err)}, 500)

    def _file(self, full):
        if not os.path.isfile(full):
            return self._json({'error': 'not found'}, 404)
        data = open(full, 'rb').read()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json' if full.endswith('.json')
                         else 'application/octet-stream')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    archive.seed_if_empty()
    providers = load_providers()
    Handler.sessions = Sessions(providers)
    print(f'Tales Through Things — AI: {providers.name}, {len(archive.list_memories())} memories in the archive')
    print(f'Passcode: {"on" if PASSCODE else "off"}')

    if BEHIND_PROXY:
        # the web proxy in front (Caddy) does HTTPS and forwards to us on localhost
        httpd = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), partial(Handler, directory=WEB))
        print(f'Listening on http://127.0.0.1:{PORT} (behind the HTTPS proxy)', flush=True)
    else:
        ips, hostname = local_ips(), local_hostname()
        key, crt = make_server_cert(ips, hostname)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(crt, key)
        httpd = http.server.ThreadingHTTPServer(('0.0.0.0', PORT), partial(Handler, directory=WEB))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        print('Open on the iPad:')
        for host in ([hostname] if hostname else []) + ips:
            print(f'  https://{host}:{PORT}')
        print('Live reload is on. Ctrl+C to stop.', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    sys.exit(main())
