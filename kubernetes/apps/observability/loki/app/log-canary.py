"""Numbered stdout -> OTel -> Loki delivery probe; standard library only."""
from __future__ import annotations

import json
import os
import signal
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Ledger:
    def __init__(self, started, run_id, node, capacity=512):
        self.started = started
        self.run_id = run_id
        self.node = node
        self.capacity = capacity
        self.pending = {}
        self.written = 0
        self.confirmed = 0
        self.query_failures = 0
        self.overflow = 0
        self.evicted_since = None
        self.last_emission = started
        self.last_query = started
        self.lock = threading.Lock()

    def emit(self, now):
        with self.lock:
            self.written += 1
            sequence = self.written
            self.pending[sequence] = now
            self.last_emission = now
            if len(self.pending) > self.capacity:
                oldest = next(iter(self.pending))
                stamp = self.pending.pop(oldest)
                self.evicted_since = stamp if self.evicted_since is None else min(stamp, self.evicted_since)
                self.overflow += 1
        return json.dumps({'message': 'anton-log-canary', 'run': self.run_id,
                           'node': self.node, 'seq': sequence, 'emitted_at': now, 'level': 'info'}, separators=(',', ':'))

    def confirm(self, lines, now):
        sequences = set()
        for line in lines:
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                continue
            if (isinstance(record, dict) and record.get('message') == 'anton-log-canary'
                    and record.get('run') == self.run_id and type(record.get('seq')) is int):
                sequences.add(record['seq'])
        with self.lock:
            for sequence in sequences:
                if sequence in self.pending:
                    self.pending.pop(sequence)
                    self.confirmed += 1
            self.last_query = now

    def failed_query(self):
        with self.lock:
            self.query_failures += 1

    def query_start(self, now):
        with self.lock:
            return min(self.pending.values(), default=now - 30) - 1

    def metrics(self, now):
        with self.lock:
            oldest = min(self.pending.values(), default=now)
            if self.evicted_since is not None:
                oldest = min(oldest, self.evicted_since)
            counters = {'written': self.written, 'confirmed': self.confirmed,
                        'query_failures': self.query_failures, 'overflow': self.overflow}
            gauges = {'pending_records': len(self.pending),
                      'oldest_unconfirmed_age_seconds': max(0, now - oldest),
                      'last_emission_timestamp_seconds': self.last_emission,
                      'last_successful_query_timestamp_seconds': self.last_query,
                      'started_timestamp_seconds': self.started}
        lines = []
        for name, value in counters.items():
            metric = 'log_canary_' + name + '_total'
            lines += ['# TYPE ' + metric + ' counter', metric + ' ' + str(value)]
        for name, value in gauges.items():
            metric = 'log_canary_' + name
            lines += ['# TYPE ' + metric + ' gauge', metric + ' ' + str(value)]
        return '\n'.join(lines) + '\n'


def query_url(base, pod, run_id, start, end):
    selector = '{k8s_namespace_name="observability",k8s_container_name="canary"}'
    query = selector + ' | k8s_pod_name=' + json.dumps(pod)
    query += ' |= ' + json.dumps('"run":' + json.dumps(run_id))
    return base.rstrip('/') + '/loki/api/v1/query_range?' + urllib.parse.urlencode({
        'query': query, 'start': int(start * 1e9), 'end': int(end * 1e9),
        'limit': 5000, 'direction': 'backward'})


def check_once(ledger, base, pod, timeout=5):
    now = time.time()
    url = query_url(base, pod, ledger.run_id, ledger.query_start(now), now)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('query response exceeds bound')
        data = json.loads(raw)
        if data.get('status') != 'success' or data.get('data', {}).get('resultType') != 'streams':
            raise ValueError('invalid query response')
        lines = [entry[1] for stream in data['data']['result'] for entry in stream['values']]
        ledger.confirm(lines, time.time())
        return True
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        ledger.failed_query()
        return False


def main():
    base = os.environ.get('LOKI_URL', 'http://loki.observability.svc.cluster.local:3100')
    if urllib.parse.urlsplit(base).scheme not in {'http', 'https'}:
        raise ValueError('LOKI_URL requires HTTP or HTTPS')
    pod = os.environ['POD_NAME']
    ledger = Ledger(time.time(), uuid.uuid4().hex, os.environ.get('NODE_NAME', 'unknown'))
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path not in {'/metrics', '/ready'}:
                self.send_error(404)
                return
            body = ledger.metrics(time.time()) if self.path == '/metrics' else 'ready\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.end_headers()
            self.wfile.write(body.encode())

    def emit():
        while not stop.wait(10):
            print(ledger.emit(time.time()), flush=True)

    def check():
        while not stop.is_set():
            check_once(ledger, base, pod)
            stop.wait(10)

    server = ThreadingHTTPServer(('0.0.0.0', 3500), Handler)
    threads = [threading.Thread(target=target, daemon=True)
               for target in (emit, check, server.serve_forever)]
    for thread in threads:
        thread.start()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    stop.wait()
    server.shutdown()
    server.server_close()
    for thread in threads:
        thread.join(timeout=6)


if __name__ == '__main__':
    main()
