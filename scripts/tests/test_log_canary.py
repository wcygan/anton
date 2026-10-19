"""Exercise exact numbered-log acknowledgement, failure deadlines and controls."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, MagicMock
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


APP = load('probe', 'kubernetes/apps/observability/loki/app/log-canary.py')
HARNESS = load('harness', 'scripts/verify-log-canary.py')


class LogCanary(unittest.TestCase):
    def setUp(self):
        self.ledger = APP.Ledger(100, 'this-run', 'node-a', capacity=3)

    def metric(self, name, now=300):
        return HARNESS.metric(self.ledger.metrics(now), 'log_canary_' + name)

    def test_exact_ids_confirm_out_of_order_and_ignore_duplicates(self):
        lines = [self.ledger.emit(110), self.ledger.emit(120), self.ledger.emit(130)]
        self.ledger.confirm([lines[2], lines[0], lines[0]], 140)
        self.assertEqual(self.metric('confirmed_total'), 2)
        self.assertEqual(self.metric('pending_records'), 1)
        self.assertEqual(self.metric('oldest_unconfirmed_age_seconds'), 180)
        self.ledger.confirm([lines[1]], 301)
        self.assertEqual(self.metric('confirmed_total'), 3)
        self.assertEqual(self.metric('oldest_unconfirmed_age_seconds', 302), 0)

    def test_stale_run_boolean_future_and_invalid_lines_cannot_acknowledge(self):
        record = json.loads(self.ledger.emit(110))
        for changes in [{'run': 'previous'}, {'seq': True}, {'seq': 99}, {'message': 'other'}]:
            self.ledger.confirm([json.dumps(dict(record, **changes)), '{}', 'null', 'not-json'], 140)
        self.assertEqual(self.metric('confirmed_total'), 0)
        self.assertEqual(self.metric('oldest_unconfirmed_age_seconds', 410), 300)

    def test_overflow_is_bounded_and_latches_oldest_failure(self):
        lines = [self.ledger.emit(now) for now in [110, 120, 130, 140]]
        self.ledger.confirm(lines, 150)
        self.assertEqual(self.metric('confirmed_total'), 3)
        self.assertEqual(self.metric('overflow_total'), 1)
        self.assertEqual(self.metric('pending_records'), 0)
        self.assertEqual(self.metric('oldest_unconfirmed_age_seconds', 410), 300)

    def response(self, body):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(body).encode()
        return response

    def test_http_queries_acknowledge_only_returned_numbered_records(self):
        line = self.ledger.emit(110)
        body = {'status': 'success', 'data': {'resultType': 'streams', 'result': [{'values': [['1', line]]}]}}
        with patch.object(APP.urllib.request, 'urlopen', return_value=self.response(body)):
            self.assertTrue(APP.check_once(self.ledger, 'http://loki', 'pod'))
        self.assertEqual(self.metric('confirmed_total'), 1)

    def test_empty_query_does_not_confirm_missing_record(self):
        self.ledger.emit(110)
        body = {'status': 'success', 'data': {'resultType': 'streams', 'result': []}}
        with patch.object(APP.urllib.request, 'urlopen', return_value=self.response(body)):
            self.assertTrue(APP.check_once(self.ledger, 'http://loki', 'pod'))
        self.assertEqual(self.metric('confirmed_total'), 0)
        self.assertEqual(self.metric('oldest_unconfirmed_age_seconds', 410), 300)

    def test_failed_or_malformed_http_does_not_advance_success_or_deadline(self):
        self.ledger.emit(110)
        for body in [[], {}, {'status': 'error'}, {'status': 'success', 'data': None},
                     {'status': 'success', 'data': {'resultType': 'streams', 'result': [{}]}}]:
            with self.subTest(body=body), patch.object(APP.urllib.request, 'urlopen', return_value=self.response(body)):
                self.assertFalse(APP.check_once(self.ledger, 'http://loki', 'pod'))
        with patch.object(APP.urllib.request, 'urlopen', side_effect=TimeoutError):
            self.assertFalse(APP.check_once(self.ledger, 'http://loki', 'pod'))
        self.assertEqual(self.metric('query_failures_total'), 6)
        self.assertEqual(self.metric('last_successful_query_timestamp_seconds'), 100)
        self.assertEqual(self.metric('oldest_unconfirmed_age_seconds', 410), 300)

    def test_query_preserves_index_contract_and_limits_response(self):
        url = APP.query_url('http://loki/', 'pod-a', 'run-a', 100, 200)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(query['query'], ['{k8s_namespace_name="observability",k8s_container_name="canary"} | k8s_pod_name="pod-a" |= "\\"run\\":\\"run-a\\""'])
        self.assertEqual(query['limit'], ['5000'])
        self.assertEqual(query['start'], ['100000000000'])

    def test_negative_control_withholds_exactly_one_json_record(self):
        job = HARNESS.negative_control('canary-control')
        self.assertEqual(job['kind'], 'Job')
        self.assertEqual(job['spec']['backoffLimit'], 0)
        self.assertNotIn('name', job['spec']['template']['metadata'])
        pod = job['spec']['template']
        script = pod['spec']['containers'][0]['args'][0]
        awk_script = script.split("awk '", 1)[1][:-1]
        lines = [self.ledger.emit(now) for now in [110, 120, 130]]
        result = subprocess.run(['awk', awk_script], input='\n'.join(lines)+'\n', text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout, '\n'.join(lines[1:])+'\n')
        self.assertEqual(result.stderr, 'negative-control withheld log='+lines[0]+'\n')
        self.assertEqual(pod['spec']['activeDeadlineSeconds'], 420)
        self.assertFalse(pod['spec']['automountServiceAccountToken'])
        self.assertEqual(pod['spec']['restartPolicy'], 'Never')
        self.assertIn('loki-log-canary-', pod['spec']['volumes'][0]['configMap']['name'])
