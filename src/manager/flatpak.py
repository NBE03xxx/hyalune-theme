# SPDX-License-Identifier: MIT
"""Flatpak policies; existing per-app ownership and one native journal."""
import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from . import profile


def prepare(home, desired, explicit, output, loader, environment):
    discovery=loader('flatpak-discovery');ops=[];report=[]
    policies=copy.deepcopy(desired.get('flatpak',{}))
    for app in explicit: policies.setdefault(app,{'mode':'follow'})
    if desired['format']==2: desired['flatpak']=policies
    active={app:policy for app,policy in policies.items() if policy['mode']!='hold'}
    if not active:return ops,report
    inventory=discovery.scan(home,env=environment);rows={r['app']:r for r in inventory['apps']}
    running=set(subprocess.check_output(['flatpak','ps','--columns=application'],env=environment,text=True,timeout=20).splitlines()) if inventory['available'] else set()
    for app,policy in sorted(active.items()):
        row=rows.get(app);reason=None
        if not row:reason='未導入または検出できません。'
        elif app in running:reason='起動中です。終了後の適用まで保留します。'
        elif row['toolkit'] not in ('gtk3','gtk4'):reason='対応するGTK系と確認できません。'
        elif row['status'] not in ('candidate','already-managed'):reason=row.get('reason','競合しています。')
        if reason:
            if app in explicit:raise ValueError('アプリを変更できません: '+app+' / '+reason)
            report.append({'app':app,'status':'deferred','reason':reason});continue
        child=discovery.app_module();child.configure_targets(app)
        try:
            child.core.safe(home/child.core.STATE/'pending.json')
            if (home/child.core.STATE/'pending.json').exists():raise ValueError('アプリの中断を先に復旧してください。')
            source=output/app
            profile.generate(profile.for_app(desired,policy),Path(__file__).resolve().parents[1]/'scss',source)
            child.ARGS=SimpleNamespace(app=app,source=str(source));child.APP_INFO=row['info']
            mode='update' if (home/child.core.ACTIVE).exists() else 'apply'
            planned,_=child.make_plan(home,None,mode,source)
            owner=next(op for op in planned if op['name']==child.core.ACTIVE)
            record=json.loads(child.core.contents(owner['after']))
            record['manager']={'format':2,'policy':policy,'profile_sha256':profile.digest(desired),
                               'material_sha256':profile.app_material_digest(desired,policy)}
            owner['after']=child.core.image(child.core.canonical(record),0o600)
            ops.extend(planned);report.append({'app':app,'status':'planned','operation':mode,'policy':policy})
        except (OSError,ValueError,KeyError,TypeError) as error:
            if app in explicit:raise
            report.append({'app':app,'status':'deferred','reason':str(error)})
    return ops,report
