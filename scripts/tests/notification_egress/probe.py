"""Read-only connection checks; run in the approved temporary Pod.

Usage: python3 - CONFIG_JSON before|after <probe.py
CONFIG_JSON contains discovered addresses; retain it outside committed source.
"""
import concurrent.futures
import json
import socket
import ssl
import struct
import sys
import time


def main():
    config = json.loads(sys.argv[1])
    phase = sys.argv[2]
    assert phase in ['before', 'after']

    def connection(case):
        started = time.monotonic()
        connected = False
        result = 'unknown'
        try:
            with socket.create_connection((case['host'], case['port']), timeout=3) as sock:
                if case.get('api'):
                    context = ssl.create_default_context(cafile='/var/run/anton-ca/ca.crt')
                    with context.wrap_socket(sock, server_hostname='kubernetes.default.svc') as tls:
                        tls.sendall(b'GET /version HTTP/1.1\r\nHost: kubernetes.default.svc\r\nConnection: close\r\n\r\n')
                        status = int(tls.recv(4096).split(b' ', 2)[1])
                        assert status in [200, 401, 403]
                connected = True
                result = 'connected'
        except Exception as error:
            result = type(error).__name__
        allowed = phase == 'before' or case['allowed_after']
        # A refused connection is not evidence that a network policy blocked it.
        passed = connected if allowed else result == 'TimeoutError'
        return {'case': case['name'], 'expected_allowed': allowed, 'result': result,
                'passed': passed, 'seconds': round(time.monotonic() - started, 2)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(connection, config['connections']))
    for transport, label in [(socket.SOCK_DGRAM, 'dns_udp'), (socket.SOCK_STREAM, 'dns_tcp')]:
        try:
            packet = struct.pack('!HHHHHH', 1234, 0x100, 1, 0, 0, 0)
            packet += b''.join(bytes([len(p)]) + p.encode() for p in 'kubernetes.default.svc.cluster.local'.split('.')) + b'\0\0\1\0\1'
            with socket.socket(socket.AF_INET, transport) as sock:
                sock.settimeout(3)
                sock.connect((config['dns'], 53))
                sock.sendall((struct.pack('!H', len(packet)) if transport == socket.SOCK_STREAM else b'') + packet)
                response = sock.recv(4096)
                if transport == socket.SOCK_STREAM:
                    length = struct.unpack('!H', response[:2])[0]
                    response = response[2:]
                    while len(response) < length:
                        part = sock.recv(length - len(response))
                        assert part
                        response += part
            assert len(response) >= 12 and struct.unpack('!HHHHHH', response[:12])[3] > 0
            results.append({'case': label, 'result': 'answered', 'passed': True})
        except Exception as error:
            results.append({'case': label, 'result': type(error).__name__, 'passed': False})
    report = {'phase': phase, 'results': results, 'passed': all(r['passed'] for r in results)}
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
