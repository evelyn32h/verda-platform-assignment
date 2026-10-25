"""State-transition tests with a simulated nftables/systemd backend, never a VM."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('admin_access', ROOT/'scripts/remote/admin-access.py')
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)


def rule(source, handle, comment=None):
    item = {'handle': handle, 'expr': [
        {'match': {'left': {'payload': {'protocol': 'ip', 'field': 'saddr'}}, 'right': source}},
        {'match': {'left': {'payload': {'protocol': 'tcp', 'field': 'dport'}}, 'right': 22}},
        {'accept': None}]}
    if comment:
        item['comment'] = comment
    return item


class AdminAccessTests(unittest.TestCase):
    def setUp(self):
        directory = ROOT/'.local/admin-access-tests'
        directory.mkdir(parents=True, exist_ok=True)
        assert directory.resolve().is_relative_to(ROOT.resolve())
        self.temp = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root/'firewall.nft'
        self.registry = self.root/'admin-cidrs.txt'
        self.original = 'table inet verda_platform {\n chain input {\n  type filter hook input priority -10; policy drop;\n  ip saddr 81.226.0.124 tcp dport 22 accept\n  tcp dport { 80, 443 } accept\n }\n}\n'
        self.config.write_text(self.original)
        self.managed = self.root/'managed'
        self.managed.touch()
        self.runtime = [rule('81.226.0.124', 10), {'handle': 20, 'expr': [{'match': {'left': {'payload': {'protocol': 'tcp', 'field': 'dport'}}, 'right': {'set': [80, 443]}}}, {'accept': None}]}]
        self.before = copy.deepcopy(self.runtime)
        self.calls = []
        patches = [patch.object(access, 'CONFIG', self.config), patch.object(access, 'REGISTRY', self.registry),
                   patch.object(access, 'BACKUPS', self.root/'backups'), patch.object(access, 'MANAGED', self.managed),
                   patch.object(access.socket, 'gethostname', return_value='verda-k3s-server'),
                   patch.object(access, 'rules', side_effect=lambda: copy.deepcopy(self.runtime)),
                   patch.object(access, 'run', side_effect=self.fake_run),
                   patch.object(access.subprocess, 'run', return_value=types.SimpleNamespace(returncode=3)),
                   patch.object(access.os, 'chown', create=True)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def fake_run(self, *args, data=None):
        self.calls.append((args, data))
        if args[:3] == ('nft', '-f', '-'):
            source = re.search(r'ip saddr ([0-9./]+)', data).group(1)
            comment = re.search(r'comment "([^"]+)"', data).group(1)
            self.runtime.insert(0, rule(source, 99, comment))
        elif args[:3] == ('nft', 'delete', 'rule'):
            handle = int(args[-1])
            self.runtime = [item for item in self.runtime if item['handle'] != handle]
        return ''

    def add(self):
        result = access.add('92.34.3.207/32', 600)
        return result, Path(result['state_file'])

    def test_add_is_narrow_and_rollback_is_armed_first(self):
        result, state = self.add()
        self.assertEqual(result['status'], 'PENDING')
        self.assertEqual(access.remove_owned_line(self.config.read_text(), json.loads(state.read_text())['comment'], '92.34.3.207/32'), self.original)
        self.assertEqual(self.registry.read_text().splitlines(), ['81.226.0.124/32', '92.34.3.207/32'])
        self.assertEqual([r for r in self.runtime if r.get('handle') != 99], self.before)
        arm = next(i for i, (a, _) in enumerate(self.calls) if a[0] == 'systemd-run')
        apply = next(i for i, (a, _) in enumerate(self.calls) if a[:3] == ('nft', '-f', '-'))
        self.assertLess(arm, apply)
        self.assertTrue(all(a[0] in ('nft', 'systemd-run') for a, _ in self.calls))

    def test_rollback_restores_original_runtime_and_persistence(self):
        _, state = self.add()
        access.rollback(state)
        self.assertEqual(self.runtime, self.before)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertFalse(self.registry.exists())
        self.assertEqual(json.loads(state.read_text())['status'], 'ROLLED_BACK')

    def test_confirmation_requires_the_new_source(self):
        _, state = self.add()
        with patch.dict(os.environ, {'SSH_CONNECTION': '81.226.0.124 50000 95.133.252.141 22'}):
            with self.assertRaises(RuntimeError):
                access.confirm(state)
        self.assertEqual(json.loads(state.read_text())['status'], 'PENDING')

    def test_confirmation_cancels_only_its_timer(self):
        _, state = self.add()
        with patch.dict(os.environ, {'SSH_CONNECTION': '92.34.3.207 50000 95.133.252.141 22'}):
            result = access.confirm(state)
        self.assertEqual(result['status'], 'CONFIRMED')
        self.assertEqual(self.calls[-1][0][:2], ('systemctl', 'stop'))
        self.assertTrue(self.calls[-1][0][2].endswith('.timer'))
        access.rollback(state)
        self.assertTrue(any(r.get('handle') == 99 for r in self.runtime))

    def test_future_regeneration_keeps_old_and_new_sources(self):
        self.assertEqual(access.collect(self.original, '92.34.3.207/32\n', '81.226.0.124'), ['81.226.0.124/32', '92.34.3.207/32'])

    def test_refuses_wide_or_ipv6_sources(self):
        for source in ('0.0.0.0/0', '92.34.3.0/24', '::1/128'):
            with self.assertRaises(ValueError):
                access.cidr(source)

    def test_pending_change_blocks_regeneration(self):
        self.add()
        with self.assertRaises(RuntimeError):
            access.no_pending_change()


if __name__ == '__main__':
    unittest.main()
