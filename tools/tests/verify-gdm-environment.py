#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check the GDM environment boundary without modifying any system state."""
import importlib.util
from pathlib import Path
import subprocess
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('gdm', Path(__file__).resolve().parents[1]/'manage-gdm.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
passed = []
for name, facts, expected in [
    ('KVM remains supported', ('kvm', '', ''), 'kvm'),
    ('T16 physical trial', ('none', 'LENOVO', 'ThinkPad T16 Gen 4'), 't16-trial'),
    ('unknown physical host', ('none', '', ''), None),
    ('other Lenovo', ('none', 'LENOVO', 'ThinkPad X1'), None),
    ('vendor mismatch', ('none', 'OTHER', 'ThinkPad T16 Gen 4'), None),
    ('other hypervisor', ('vmware', 'LENOVO', 'ThinkPad T16 Gen 4'), None),
    ('container cannot masquerade as physical', ('container-other', 'LENOVO', 'ThinkPad T16 Gen 4'), None),
]:
    try:
        actual = g.validate_machine(*facts)
        assert expected is not None and actual == expected, name
    except ValueError:
        assert expected is None, name
    passed.append(name)
for code, output in [(2, ''), (1, 'kvm'), (1, '')]:
    with patch.object(g.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, output, '')):
        try:
            g.machine_scope()
            raise AssertionError('ambiguous detection accepted')
        except ValueError:
            passed.append('ambiguous detection rejected: '+repr((code, output)))
with patch.object(g.os, 'geteuid', return_value=1000):
    try:
        g.guard()
        raise AssertionError('non-root accepted')
    except ValueError:
        passed.append('normal user needs sudo')
with patch.object(g.os, 'geteuid', return_value=0), patch.object(g, 'machine_scope', side_effect=ValueError('unsupported machine')):
    try:
        g.guard(restoring=True)
        raise AssertionError('restoration bypassed machine boundary')
    except ValueError:
        passed.append('restore still checks environment')
print('PASS:', len(passed), 'GDM environment checks')
