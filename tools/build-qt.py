#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the three explicitly supported Qt Wayland decoration ABIs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
VARIANTS = {'native5': ('5','5.15.18','qt5'),
            'native6': ('6','6.10.2','qt6-6.10'),
            'flatpak6': ('6','6.11.3','qt6-6.11')}


def source_digest():
    files = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((ROOT/'src/qt').rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    return hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()


def build(name, native, sdk, runtime, output):
    major,abi,source = VARIANTS[name]
    includes = native/'include/x86_64-linux-gnu'/('qt'+major)
    libs = Path('/usr/lib/x86_64-linux-gnu')
    moc = [str(native/('lib/qt5/bin/moc' if major=='5' else 'lib/qt6/libexec/moc'))]
    if name == 'flatpak6':
        includes = sdk/'include'
        libs = runtime/'lib/x86_64-linux-gnu'
        moc = [str(runtime/'lib64/ld-linux-x86-64.so.2'), '--library-path',
               str(libs)+':'+str(runtime/'lib'), str(runtime/'lib/libexec/moc')]
    actual = (libs/('libQt'+major+'Core.so.'+major)).resolve().name
    if actual != 'libQt'+major+'Core.so.'+abi:
        raise ValueError(f'{name}: expected Qt {abi}, found {actual}')
    flags = ['-I'+str(includes), '-I'+str(native/'include')]
    for module in ['Core','Gui','DBus','WaylandClient','Svg','XkbCommonSupport','EglSupport','WaylandGlobal','OpenGL','Network']:
        path = includes/('Qt'+module)
        flags += ['-I'+str(path), '-I'+str(path/abi), '-I'+str(path/abi/('Qt'+module))]
    target = output/name/'wayland-decoration-client/libhyalune.so'
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hyalune-qt-build-') as directory:
        base = Path(directory)
        work = base/source
        shutil.copytree(ROOT/'src/qt'/source,work)
        for file in ['theme-state.h','theme-state.cpp']:
            shutil.copyfile(ROOT/'src/qt'/file,base/file)
        def run(args):
            subprocess.run(args,cwd=work,check=True)
        run([*moc,*flags,'main.cpp','-o','main.moc'])
        run([*moc,*flags,'../theme-state.h','-o','moc_theme-state.cpp'])
        sources = ['main.cpp','../theme-state.cpp','moc_theme-state.cpp']
        if major == '6':
            run([*moc,*flags,'qwaylandadwaitadecoration_p.h','-o','moc_qwaylandadwaitadecoration_p.cpp'])
            sources.append('qwaylandadwaitadecoration.cpp')
        link = [str(libs/('libQt'+major+lib+'.so.'+major)) for lib in ['WaylandClient','Gui','Core','DBus']]
        if major == '6':
            link.append(str(libs/'libQt6Svg.so.6'))
        run(['g++','-std=c++17','-O2','-fPIC','-shared',*flags,*sources,
             '-Wl,-rpath-link,'+str(libs),*link,'-o',str(target)])
    return {'abi':abi,'major':int(major),'path':str(target.relative_to(output)),
            'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native-prefix',type=Path,default=Path('/usr'))
    p.add_argument('--flatpak-sdk-prefix',type=Path,required=True)
    p.add_argument('--flatpak-runtime-prefix',type=Path,required=True)
    p.add_argument('--output',type=Path,default=ROOT/'build/Hyalune-Qt')
    args=p.parse_args()
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    variants={name:build(name,args.native_prefix.resolve(),args.flatpak_sdk_prefix.resolve(),
                         args.flatpak_runtime_prefix.resolve(),output) for name in VARIANTS}
    manifest={'format':1,'component':'hyalune-qt','version':'0.1.0-qt-preview.1',
              'source_sha256':source_digest(),'variants':variants}
    (output/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    print(output)


if __name__=='__main__':
    main()
