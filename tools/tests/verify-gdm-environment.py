#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check the hardware-independent GDM boundary without system changes."""
import importlib.util,json
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('gdm',Path(__file__).resolve().parents[1]/'manage-gdm.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
loader=b"themeResourceName: 'gdm-theme.gresource', stylesheetName: 'gdm.css'"
checks=[]
def check(name,value):checks.append({'name':name,'passed':bool(value)});assert value,name
for version in ['50.0','50.1','50.2.1']:
 g.validate_environment('ubuntu','26.04',version,loader);check('supported Ubuntu/Shell/resource layout: '+version,True)
for facts in [('debian','26.04','50.1',loader),('ubuntu','25.10','50.1',loader),('ubuntu','26.04','49.9',loader),('ubuntu','26.04','51.0',loader),('ubuntu','26.04','50.invalid',loader),('ubuntu','26.04','50.1',b"stylesheetName: 'gdm.css'"),('ubuntu','26.04','50.1',b"themeResourceName: 'gdm-theme.gresource'"),('ubuntu','26.04','50.1',b'')]:
 try:g.validate_environment(*facts)
 except ValueError:check('unsupported OS/Shell/loader rejected: '+repr(facts[:3])+'/'+str(len(facts[3])),True)
 else:raise AssertionError('unsupported layout accepted')
# Guard must not query machine/DMI identity or require a virtualization utility.
actual_path=g.Path
class ReadOnlyFacts:
 def __init__(self,path):self.path=path
 def read_text(self):
  assert self.path=='/etc/os-release',self.path
  return 'ID=ubuntu\nVERSION_ID="26.04"\n'
with patch.object(g.os,'geteuid',return_value=0),patch.object(g,'Path',ReadOnlyFacts),patch.object(g,'call',return_value='GNOME Shell 50.1') as call,patch.object(g.subprocess,'check_output',return_value=loader),patch.object(g,'safe') as safe:
 g.guard();check('generic guard uses only OS/Shell/loader and bounded paths',call.call_args.args==('gnome-shell','--version') and safe.call_count==2)
with patch.object(g.os,'geteuid',return_value=1000):
 for restoring in [False,True]:
  try:g.guard(restoring=restoring)
  except ValueError:check('normal user rejected / restoring='+str(restoring),True)
  else:raise AssertionError('normal user accepted')
with patch.object(g.os,'geteuid',return_value=0),patch.object(g,'Path',side_effect=AssertionError('restore re-read changed OS')),patch.object(g,'call',side_effect=AssertionError('restore queried Shell')),patch.object(g,'safe') as safe:
 g.guard(restoring=True);check('owned restore remains available after OS changes',safe.call_count==2)
print(json.dumps({'status':'passed','checks':checks},indent=2))
