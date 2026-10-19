"""Verify a signed, uncached S3 GET through this gateway; export bounded results."""
import datetime
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SIZE = 65536
SHA256 = hashlib.sha256(bytes(SIZE)).hexdigest()
URL = 'http://127.0.0.1:8333/s3-read-probe/fixture-v1'


def signed_request(url, access, secret, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp, day = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
    parsed = urllib.parse.urlsplit(url)
    empty = hashlib.sha256(b'').hexdigest()
    headers = {'host': parsed.netloc, 'x-amz-content-sha256': empty, 'x-amz-date': stamp}
    names = ';'.join(sorted(headers))
    canonical = '\n'.join(['GET', parsed.path, parsed.query,
                           ''.join(k + ':' + headers[k] + '\n' for k in sorted(headers)), names, empty])
    scope = day + '/us-east-1/s3/aws4_request'
    to_sign = 'AWS4-HMAC-SHA256\n' + stamp + '\n' + scope + '\n' + hashlib.sha256(canonical.encode()).hexdigest()
    key = ('AWS4' + secret).encode()
    for part in [day, 'us-east-1', 's3', 'aws4_request']:
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    headers['authorization'] = f'AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={names}, Signature={signature}'
    headers['cache-control'] = 'no-cache'
    return urllib.request.Request(url, headers=headers)


class ReadDeadline(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def verify(url, access, secret):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(signed_request(url, access, secret), timeout=10) as response:
            body = response.read(SIZE + 1)
            if response.status != 200 or len(body) != SIZE:
                return {'ok': False, 'reason': 'status_or_length'}
            if hashlib.sha256(body).hexdigest() != SHA256:
                return {'ok': False, 'reason': 'checksum'}
        return {'ok': True, 'reason': 'verified'}
    except ReadDeadline:
        raise
    except urllib.error.HTTPError as error:
        error.close()
        return {'ok': False, 'reason': 'read_error'}
    except Exception:
        return {'ok': False, 'reason': 'read_error'}


def check(url=URL, timeout=15):
    def expired(signum, frame):
        raise ReadDeadline()

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        directory = Path(os.environ.get('CREDENTIALS_DIRECTORY', '/credentials'))
        access = (directory / 'access-key').read_text().strip()
        secret = (directory / 'secret-key').read_text().strip()
        return verify(url, access, secret)
    except ReadDeadline:
        return {'ok': False, 'reason': 'deadline'}
    except OSError:
        return {'ok': False, 'reason': 'credentials_unavailable'}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class Ledger:
    def __init__(self):
        self.lock = threading.Lock()
        self.completed = 0
        self.success = 0
        self.failures = 0

    def record(self, result, now):
        with self.lock:
            self.completed = now
            self.success = int(result['ok'])
            self.failures = 0 if result['ok'] else self.failures + 1

    def metrics(self):
        with self.lock:
            return ''.join(f'seaweedfs_s3_read_probe_{name} {value}\n' for name, value in [
                ('last_completed_timestamp_seconds', self.completed),
                ('success', self.success), ('consecutive_failures', self.failures)])


def serve():
    ledger = Ledger()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ['/metrics', '/ready']:
                self.send_error(404)
                return
            body = ledger.metrics().encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('0.0.0.0', 9328), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    while True:
        started = time.monotonic()
        result = check()
        ledger.record(result, time.time())
        print(json.dumps({'event': 's3_read_probe', **result}), flush=True)
        time.sleep(max(0, 60 - (time.monotonic() - started)))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--once':
        print(json.dumps(check(sys.argv[2])))
    else:
        serve()
