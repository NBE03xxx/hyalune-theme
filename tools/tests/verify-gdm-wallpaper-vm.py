#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Test wallpaper capture and preservation in a private KVM fixture."""
import base64
import argparse
import contextlib
import io
import pwd
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

TOOLS = Path(__file__).resolve().parents[1]
HELPER = TOOLS/'gdm-wallpaper.py'
CSS = TOOLS.parent/'build/Hyalune-GDM/overlay.css'
spec = importlib.util.spec_from_file_location('gdm_fixture', TOOLS/'tests/verify-gdm-vm.py')
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)


def prepare_root_fixture(root):
    assert os.geteuid() != 0
    root.mkdir(mode=0o700, exist_ok=False)
    import gi
    gi.require_version('GdkPixbuf','2.0')
    from gi.repository import GdkPixbuf
    image=root/'desktop.png';pix=GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,False,8,80,60)
    pix.fill(0x285b62ff);pix.savev(str(image),'png',[],[])
    pix.fill(0x633e53ff);pix.savev(str(root/'replacement.png'),'png',[],[])
    key=root/'config/glib-2.0/settings/keyfile';key.parent.mkdir(parents=True)
    key.write_text("[org/gnome/desktop/interface]\ncolor-scheme='prefer-dark'\n[org/gnome/desktop/background]\npicture-uri="+repr(image.as_uri())+"\npicture-uri-dark="+repr(image.as_uri())+"\npicture-options='zoom'\npicture-opacity=100\n")
    for name in ['admin','alternatives','state']:(root/name).mkdir()
    (root/'base.gresource').write_bytes(Path('/usr/share/gnome-shell/gnome-shell-theme.gresource').read_bytes())
    print(json.dumps({'fixture':str(root),'uid':os.getuid()}))


def root_fixture(root, child_action=None, crash=0, friendly=False):
    assert os.geteuid()==0 and subprocess.check_output(['systemd-detect-virt','--vm'],text=True).strip()=='kvm'
    root=root.resolve();assert root.name.startswith('hyalune-wallpaper-root-')
    user=pwd.getpwuid(root.stat().st_uid);assert user.pw_uid!=0
    installed=subprocess.check_output(['update-alternatives','--query','gdm-theme.gresource'])
    g=fixture.setup(root);environment=g.capture_environment
    g.capture_environment=lambda u:{**environment(u),'GSETTINGS_BACKEND':'keyfile','XDG_CONFIG_HOME':str(root/'config')}
    def cli(*args, human=False):
        before=sys.argv;out=io.StringIO()
        try:
            sys.argv=['install.sh gdm',*args,*([] if human else ['--json'])]
            with contextlib.redirect_stdout(out):g.main()
        finally:sys.argv=before
        return out.getvalue() if human else json.loads(out.getvalue())
    if child_action:
        cli(child_action,'--crash-after',str(crash));return
    passed=[]
    def ok(name,value):assert value,name;passed.append(name)
    base=root/'base.gresource';g.alt('--install',g.LINK,g.GROUP,str(base),'10');g.alt('--auto',g.GROUP);original=g.alternatives()
    os.environ.pop('SUDO_UID',None);os.environ.pop('SUDO_USER',None)
    try:cli('plan');raise AssertionError('root identity was guessed')
    except ValueError as e:ok('root without caller stops before changes','sudo' in str(e) and not list(g.STATE.iterdir()))
    os.environ['SUDO_UID']=str(user.pw_uid);os.environ['SUDO_USER']=user.pw_name
    before=list(root.rglob('*'));plan=cli('plan')
    ok('root CLI plan defaults to desktop capture',plan['background']['origin']=='desktop' and plan['background']['captured_uid']==user.pw_uid)
    ok('root CLI plan leaves files and alternatives unchanged',before==list(root.rglob('*')) and g.alternatives()==original)
    if friendly:
        ok('automatic plan chooses first installation',plan['operation']=='apply')
    result=cli('set') if friendly else cli('apply','--vm-preview');owner=g.read(g.STATE/'active.json')
    ok('root CLI apply uses real runuser decoder',result['committed'] and owner['background']['captured_uid']==user.pw_uid)
    key=root/'config/glib-2.0/settings/keyfile';old_settings=key.read_bytes();(root/'desktop.png').unlink()
    plan=cli('plan') if friendly else cli('plan','--operation','update')
    if friendly:
        ok('same plan automatically chooses update',plan['operation']=='update')
        ok('human plan explains keeping saved background','更新' in cli('plan',human=True) and '保存済み' in cli('plan',human=True))
        ok('human status is readable without JSON','導入済み' in cli('status',human=True) and not cli('status',human=True).lstrip().startswith('{'))
    result=cli('set') if friendly else cli('update','--vm-preview')
    ok('root CLI update ignores deleted desktop source',result['committed'] and plan['background']==owner['background'])
    key.write_text(old_settings.decode().replace((root/'desktop.png').as_uri(),(root/'replacement.png').as_uri()))
    old_owner=g.read(g.STATE/'active.json')
    old_css=subprocess.check_output(['gresource','extract',old_owner['resource'],g.PREFIX+'gdm.css'])
    plan=cli('background','--plan') if friendly else cli('plan','--operation','set-background','--background','desktop')
    ok('root CLI replacement plan does not apply',g.read(g.STATE/'active.json')==old_owner and plan['background']['sha256']!=old_owner['background_sha256'])
    result=cli('background') if friendly else cli('set-background','--vm-preview','--background','desktop')
    owner=g.read(g.STATE/'active.json')
    ok('root CLI explicitly replaces background',result['committed'] and owner['background_sha256']==plan['background']['sha256'])
    ok('root CLI replacement preserves installed UI',subprocess.check_output(['gresource','extract',owner['resource'],g.PREFIX+'gdm.css'])==old_css)
    before=g.read(g.STATE/'active.json');before_alt=g.alternatives()
    child=subprocess.run([sys.executable,__file__,'--root-fixture',str(root),'--child-action','set' if friendly else 'update','--crash','3',*(['--friendly'] if friendly else [])],capture_output=True,text=True)
    ok('root CLI crash injected',child.returncode==90)
    pending=g.read(g.STATE/'pending.json');saved=g.STATE/'transactions'/pending['id']/'manage-gdm.py'
    spec=importlib.util.spec_from_file_location('root_saved',saved);saved_g=importlib.util.module_from_spec(spec);spec.loader.exec_module(saved_g)
    saved_g.STATE=g.STATE;saved_g.ASSETS=g.ASSETS;saved_g.LINK=g.LINK;saved_g.call=g.call;saved_g.alt=g.alt
    ok('root standalone recovery without wallpaper helper',saved_g.recover()['result']=='rolled-back' and g.read(g.STATE/'active.json')==before and g.alternatives()==before_alt)
    cli('remove') if friendly else cli('remove','--vm-preview');ok('root CLI remove restores exact alternatives',g.alternatives()==original)
    key.write_text(old_settings.decode().replace((root/'desktop.png').as_uri(),'https://example.invalid/wallpaper.png'))
    before=list(root.rglob('*'))
    try:cli('set') if friendly else cli('apply','--vm-preview');raise AssertionError('remote capture accepted')
    except ValueError as e:ok('unsupported root capture stops without writes','local file://' in str(e) and list(root.rglob('*'))==before and g.alternatives()==original)
    result=cli('set','--bundled') if friendly else cli('apply','--vm-preview','--background','bundled')
    ok('root explicit bundled fallback works',result['background']['origin']=='bundled')
    cli('remove') if friendly else cli('remove','--vm-preview')
    if friendly:
        ok('recover without redundant flag works',not cli('recover')['recovered'])
        help_text=subprocess.check_output([sys.executable,str(TOOLS/'manage-gdm.py'),'--help'],text=True)
        ok('primary help omits internal options',all(flag not in help_text for flag in ['--operation','--vm-preview','set-background','--background']))
    ok('fixture keyfile was not rewritten by capture',key.read_text()==old_settings.decode().replace((root/'desktop.png').as_uri(),'https://example.invalid/wallpaper.png'))
    ok('real GDM unchanged after root CLI tests',subprocess.check_output(['update-alternatives','--query','gdm-theme.gresource'])==installed)
    print(json.dumps({'passed':len(passed),'checks':passed},indent=2))


def main():
    assert os.geteuid() != 0
    assert subprocess.check_output(['systemd-detect-virt','--vm'],text=True).strip() == 'kvm'
    installed = subprocess.check_output(['update-alternatives','--query','gdm-theme.gresource'])
    import gi
    gi.require_version('GdkPixbuf','2.0')
    from gi.repository import GdkPixbuf
    passed=[]
    def ok(name,condition):
        assert condition,name
        passed.append(name)
    with tempfile.TemporaryDirectory(prefix='hyalune-wallpaper-') as tmp:
        root=Path(tmp)
        config=root/'config';keyfile=config/'glib-2.0/settings/keyfile';keyfile.parent.mkdir(parents=True)
        def image(name,color):
            p=root/name;pic=GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,False,8,80,60);pic.fill(color)
            pic.savev(str(p),'png',[],[]);return p
        day=image('day with space.png',0x42738fff);night=image('night.png',0x173e45ff)
        def settings(scheme='prefer-dark',dark=None,light=None,options='zoom',opacity=100):
            dark=night.as_uri() if dark is None else dark
            light=day.as_uri() if light is None else light
            keyfile.write_text("[org/gnome/desktop/interface]\ncolor-scheme="+repr(scheme)+"\n[org/gnome/desktop/background]\npicture-uri="+repr(light)+"\npicture-uri-dark="+repr(dark)+"\npicture-options="+repr(options)+"\npicture-opacity="+str(opacity)+"\n")
        environment={**os.environ,'GSETTINGS_BACKEND':'keyfile','XDG_CONFIG_HOME':str(config)}
        def capture(success=True):
            p=subprocess.run([sys.executable,str(HELPER)],env=environment,capture_output=True,text=True)
            result=json.loads(p.stdout)
            if success: assert p.returncode==0,result
            else: assert p.returncode!=0 and 'error' in result,result
            return result
        settings();dark=capture()
        ok('Dark URI chosen',dark['description']['source_key']=='picture-uri-dark')
        ok('Dark source hash',dark['description']['source_sha256']==__import__('hashlib').sha256(night.read_bytes()).hexdigest())
        png=base64.b64decode(dark['png'])
        ok('normalized PNG returned with dimensions',png.startswith(b'\x89PNG') and dark['description']['width']==80 and dark['description']['height']==60)
        ok('no source path in snapshot description',not any(str(root) in str(v) or 'file://' in str(v) for v in dark['description'].values()))
        settings(scheme='prefer-light');light=capture()
        ok('Light URI and escaped space supported',light['description']['source_key']=='picture-uri' and light['description']['source_sha256']==__import__('hashlib').sha256(day.read_bytes()).hexdigest())
        settings(scheme='default');ok('default color scheme uses normal URI',capture()['description']['source_key']=='picture-uri')
        jpeg=root/'photo.jpg';pic=GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,False,8,80,60);pic.fill(0x426e88ff);pic.savev(str(jpeg),'jpeg',[],[])
        settings(dark=jpeg.as_uri());ok('JPEG wallpaper normalized to PNG',base64.b64decode(capture()['png']).startswith(b'\x89PNG'))
        svg=root/'vector.svg';svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60"><path fill="#285b62" d="M0 0h80v60H0z"/></svg>')
        settings(dark=svg.as_uri());ok('static SVG wallpaper normalized to PNG',capture()['description']['width']==80)
        big_svg=root/'huge.svg';big_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10000" height="10000"/>')
        settings(dark=big_svg.as_uri());ok('decoded pixel limit enforced','40 million' in capture(False)['error'])
        gif=root/'animated.gif'
        gif.write_bytes(bytes.fromhex('47494638396101000100800000000000ffffff21f904000a0000002c000000000100010000020244010021f904000a0000002c00000000010001000002024c01003b'))
        settings(dark=gif.as_uri());ok('animated image rejected','Animated' in capture(False)['error'])

        settings(dark='');ok('empty Dark URI falls back to normal',capture()['description']['source_key']=='picture-uri')
        settings(options='scaled');ok('display preference recorded; GDM remains cover',capture()['description']['picture_options']=='scaled')
        for label,kwargs in [('none',{'options':'none'}),('invisible',{'opacity':0}),('no image',{'dark':'','light':''}),('remote',{'dark':'https://example.invalid/image.png'}),('missing',{'dark':(root/'absent.png').as_uri()})]:
            settings(**kwargs);result=capture(False);ok(label+' stops with a reason',bool(result['error']))
        xml=root/'slide.xml';xml.write_text('<background><static/></background>');settings(dark=xml.as_uri())
        ok('dynamic XML rejected explicitly','Dynamic XML' in capture(False)['error'])
        invalid=root/'bad.png';invalid.write_bytes(b'not an image');settings(dark=invalid.as_uri());ok('invalid image rejected',bool(capture(False)['error']))
        fifo=root/'pipe';os.mkfifo(fifo);settings(dark=fifo.as_uri());ok('non-regular file rejected without blocking','regular file' in capture(False)['error'])
        large=root/'large.png'
        with large.open('wb') as f:f.truncate(32*1024*1024+1)
        settings(dark=large.as_uri());ok('oversized source rejected','32MiB' in capture(False)['error'])
        blocked=root/'unreadable.png';blocked.write_bytes(night.read_bytes());blocked.chmod(0)
        settings(dark=blocked.as_uri());ok('unreadable source rejected','cannot read' in capture(False)['error']);blocked.chmod(0o600)
        # Real capture subprocess through the manager, with a private settings backend.
        g=fixture.setup(root)
        for name in ['admin','alternatives','state']:(root/name).mkdir()
        real_environment=g.capture_environment
        g.capture_environment=lambda user:{**real_environment(user),'GSETTINGS_BACKEND':'keyfile','XDG_CONFIG_HOME':str(config)}
        settings()
        real_capture=g.capture_desktop_background
        snapshot=real_capture()
        ok('manager verifies ordinary-user capture',snapshot['data']==png and snapshot['description']['captured_uid']==os.getuid())
        # Real alternatives database redirected to this fixture only.
        source=Path('/usr/share/gnome-shell/gnome-shell-theme.gresource');base=root/'base.gresource';base.write_bytes(source.read_bytes())
        g.alt('--install',g.LINK,g.GROUP,str(base),'10');g.alt('--auto',g.GROUP);original=g.alternatives()
        plan=g.operate('apply',CSS.read_bytes(),dry=True,background=snapshot)
        ok('plan shows desktop capture without changing alternatives',plan['background']['origin']=='desktop' and g.alternatives()==original and not (g.STATE/'pending.json').exists())
        g.operate('apply',CSS.read_bytes(),background=snapshot);owner=g.read(g.STATE/'active.json')
        stored=subprocess.check_output(['gresource','extract',owner['resource'],g.PREFIX+'hyalune-background.png'])
        ok('desktop image actually embedded',stored==png)
        css=subprocess.check_output(['gresource','extract',owner['resource'],g.PREFIX+'gdm.css'])
        ok('CSS uses managed PNG; no HOME dependency',b'hyalune-background.png' in css and str(root).encode() not in css)
        hc=subprocess.check_output(['gresource','extract',owner['resource'],g.PREFIX+'gdm-high-contrast.css'])
        standard_hc=subprocess.check_output(['gresource','extract',str(base),g.PREFIX+'gnome-shell-high-contrast.css'])
        ok('High Contrast bytes unchanged',hc==standard_hc)
        # Deleting the original and changing today's desktop must not affect update.
        night.unlink();settings(dark=day.as_uri())
        def no_capture(*a):raise AssertionError('Update tried to recapture the desktop')
        g.capture_desktop_background=no_capture
        g.operate('update',CSS.read_bytes()+b'\n/* update */\n')
        updated=g.read(g.STATE/'active.json')
        ok('update retains original image and metadata',g.owned_background(updated)==snapshot)
        ok('no private image bytes in owner JSON','png' not in updated and 'data' not in updated)
        # Explicit replacement uses today's image but must keep installed UI,
        # even if the checkout's CSS has unrelated edits.
        settings(dark=day.as_uri())
        g.capture_desktop_background=real_capture
        replacement=g.capture_desktop_background()
        g.capture_desktop_background=no_capture
        def resources(owner):
            return {n:subprocess.check_output(['gresource','extract',owner['resource'],n]) for n in g.call('gresource','list',owner['resource']).splitlines()}
        old_files=resources(updated)
        g.operate('set-background',b'not the installed UI',background=replacement)
        replaced=g.read(g.STATE/'active.json');new_files=resources(replaced)
        ok('explicit replacement uses the new image',replaced['background_sha256']==replacement['description']['sha256'] and replaced['background_sha256']!=updated['background_sha256'])
        ok('all other installed resources preserved',all(old_files[n]==new_files[n] for n in old_files if not n.endswith('/hyalune-background.png')) and old_files.keys()==new_files.keys())
        ok('installed overlay metadata preserved',replaced['overlay_sha256']==updated['overlay_sha256'])
        updated=replaced
        # Interrupt a change back to the old picture; recover must keep the new one.
        replace_data=root/'snapshot.json';replace_data.write_text(json.dumps({'png':base64.b64encode(snapshot['data']).decode(),'description':snapshot['description']}))
        crash_source=root/'replace-crash.py'
        crash_source.write_text("import importlib.util,pathlib,json,base64; s=importlib.util.spec_from_file_location('f',"+repr(str(TOOLS/'tests/verify-gdm-vm.py'))+");f=importlib.util.module_from_spec(s);s.loader.exec_module(f);r=pathlib.Path("+repr(str(root))+");g=f.setup(r);d=json.loads((r/'snapshot.json').read_text());g.operate('set-background',None,crash=3,background={'data':base64.b64decode(d['png']),'description':d['description']})\n")
        interrupted=subprocess.run([sys.executable,str(crash_source)],capture_output=True,text=True)
        ok('replacement interruption injected',interrupted.returncode==90)
        recovered=g.recover()
        ok('replacement recovery keeps prior image',recovered['result']=='rolled-back' and g.read(g.STATE/'active.json')==replaced and g.owned_background(replaced)==replacement)

        # A saved standalone manager can restore without helper/source art access.
        before=g.alternatives();before_owner=updated
        child=root/'crash.py'
        child.write_text("import importlib.util,pathlib; s=importlib.util.spec_from_file_location('f',"+repr(str(TOOLS/'tests/verify-gdm-vm.py'))+");f=importlib.util.module_from_spec(s);s.loader.exec_module(f);g=f.setup(pathlib.Path("+repr(str(root))+"));g.operate('update',pathlib.Path("+repr(str(CSS))+").read_bytes(),crash=3)\n")
        p=subprocess.run([sys.executable,str(child)]);ok('desktop snapshot update interruption injected',p.returncode==90)
        pending=g.read(g.STATE/'pending.json');saved=g.STATE/'transactions'/pending['id']/'manage-gdm.py'
        saved_spec=importlib.util.spec_from_file_location('saved_gdm',saved);saved_g=importlib.util.module_from_spec(saved_spec);saved_spec.loader.exec_module(saved_g)
        saved_g.STATE=g.STATE;saved_g.ASSETS=g.ASSETS;saved_g.LINK=g.LINK;saved_g.call=g.call;saved_g.alt=g.alt
        result=saved_g.recover()
        ok('standalone recovery needs no helper or original image',result['result']=='rolled-back' and g.alternatives()==before and g.read(g.STATE/'active.json')==before_owner)
        saved_g.operate('remove',None)
        ok('standalone remove restores original alternatives',g.alternatives()==original and not (g.STATE/'active.json').exists())
        # Preserve the actual bundled image of older records across upgrades.
        g.operate('apply',CSS.read_bytes());legacy=g.read(g.STATE/'active.json');legacy.pop('background');legacy.pop('rendered_overlay_sha256');g.save(g.STATE/'active.json',legacy)
        prior=g.owned_background(legacy)
        g.bundled_background=lambda:(_ for _ in ()).throw(AssertionError('legacy update read new art'))
        g.operate('update',CSS.read_bytes()+b'\n/* legacy */\n')
        ok('legacy bundled background migrated by saved bytes',g.owned_background(g.read(g.STATE/'active.json'))['data']==prior['data'])
        g.operate('remove',None)
        ok('legacy fixture restored',g.alternatives()==original)
    ok('real GDM alternatives untouched',subprocess.check_output(['update-alternatives','--query','gdm-theme.gresource'])==installed)
    print(json.dumps({'passed':len(passed),'checks':passed},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare-root-fixture',type=Path)
    parser.add_argument('--root-fixture',type=Path)
    parser.add_argument('--child-action')
    parser.add_argument('--crash',type=int,default=0)
    parser.add_argument('--friendly',action='store_true')
    args=parser.parse_args()
    if args.prepare_root_fixture:prepare_root_fixture(args.prepare_root_fixture)
    elif args.root_fixture:root_fixture(args.root_fixture,args.child_action,args.crash,args.friendly)
    else:main()
