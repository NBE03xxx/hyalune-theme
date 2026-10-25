#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check capability policy using synthetic facts, without desktop changes."""
import copy,importlib.util,json
from pathlib import Path
s=importlib.util.spec_from_file_location('desktop_context',Path(__file__).resolve().parents[1]/'desktop-context.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
f=dict(uid=23456,euid=23456,home='/srv/users/example',home_valid=True,os_id='ubuntu',os_version='26.04',session_bus=True,shell_version='50.1',shell_pid='123',wayland_session=True)
checks=[]
def check(n,v):checks.append({'name':n,'passed':bool(v)});assert v,n
check('arbitrary normal UID/HOME and no machine identity accepted',m.validate(f)==f)
for key,value in [('uid',0),('euid',0),('home_valid',False),('session_bus',False),('os_id','other'),('os_version','25.10'),('shell_version','49.9'),('shell_version','51.0'),('wayland_session',False)]:
 d=dict(f,**{key:value})
 try:m.validate(d)
 except ValueError:check(key+'='+str(value)+' refused',True)
 else:check(key+'='+str(value)+' refused',False)
d=dict(f,os_id='other',os_version='future',shell_version='',wayland_session=False,shell_pid=None)
check('owned restoration policy can survive OS/Shell/session changes',m.validate(d,restoring=True)==d)
for key,value in [('uid',0),('home_valid',False),('session_bus',False)]:
 try:m.validate(dict(d,**{key:value}),restoring=True)
 except ValueError:check('restoration still protects '+key,True)
 else:check('restoration still protects '+key,False)
print(json.dumps({'status':'passed','checks':checks},indent=2))
