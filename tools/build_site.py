import argparse,hashlib,json,shutil,urllib.request,zipfile
from pathlib import Path
from update_changelog import update_changelog

parser=argparse.ArgumentParser()
parser.add_argument('--source',default='.')
parser.add_argument('--output',default='_site')
parser.add_argument('--archive')
parser.add_argument('--installer')
args=parser.parse_args()
source=Path(args.source).resolve(); output=Path(args.output).resolve()
manifest=json.loads((source/'.website/assets.json').read_text(encoding='utf-8-sig'))
assert manifest['url'].startswith('https://github.com/PZ099/input-showcase/releases/download/')
assert len(manifest['sha256'])==64 and 0<manifest['bytes']<128*1024*1024
archive=Path(args.archive) if args.archive else source/'_website-assets.zip'
if not args.archive:
    with urllib.request.urlopen(manifest['url'],timeout=90) as response,archive.open('wb') as target:
        count=0
        while data:=response.read(1024*1024):
            count+=len(data)
            if count>manifest['bytes']: raise ValueError('Asset archive too large')
            target.write(data)
assert archive.stat().st_size==manifest['bytes']
assert hashlib.sha256(archive.read_bytes()).hexdigest()==manifest['sha256']
output.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(archive) as z:
    seen=set()
    assert len(z.infolist())<3000 and sum(i.file_size for i in z.infolist())<256*1024*1024
    for info in z.infolist():
        path=info.filename
        assert path.startswith('assets/') and '\\' not in path and ':' not in path
        assert '..' not in Path(path).parts and not Path(path).is_absolute()
        assert (info.external_attr>>16)&0o170000 != 0o120000
        assert path.lower() not in seen
        seen.add(path.lower())
        target=(output/path).resolve()
        assert target.is_relative_to(output)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(z.read(info))
core=source/'dist' if (source/'dist/index.html').is_file() else source
for name in ['index.html','style.css','app.js','demo.js','models.json','.nojekyll','sitemap.xml','icon.png']:
    shutil.copyfile(core/name,output/name)
update_changelog(output, core/'changelog.json')
# Public IndexNow verification files live beside the project homepage.
for key_file in core.glob('*.txt'):
    if len(key_file.stem)==32 and all(c in '0123456789abcdef' for c in key_file.stem):
        assert key_file.read_text(encoding='utf-8').strip()==key_file.stem
        shutil.copyfile(key_file,output/key_file.name)
# Serve the verified installer from the same origin to preserve its save-as name.
installer_manifest=json.loads((source/'.website/installer.json').read_text(encoding='utf-8-sig'))
assert installer_manifest['filename']=='INPUT Setup.exe'
assert installer_manifest['url'].startswith('https://github.com/PZ099/input-showcase/releases/download/')
assert len(installer_manifest['sha256'])==64 and 0<installer_manifest['bytes']<128*1024*1024
installer=Path(args.installer) if args.installer else source/'_website-installer.exe'
if not args.installer:
    with urllib.request.urlopen(installer_manifest['url'],timeout=90) as response,installer.open('wb') as target:
        count=0
        while data:=response.read(1024*1024):
            count+=len(data)
            if count>installer_manifest['bytes']: raise ValueError('Installer too large')
            target.write(data)
assert installer.stat().st_size==installer_manifest['bytes']
assert hashlib.sha256(installer.read_bytes()).hexdigest()==installer_manifest['sha256']
(output/'downloads').mkdir(exist_ok=True)
shutil.copyfile(installer,output/'downloads'/installer_manifest['filename'])
cloud=source/'cloud' if (source/'cloud').is_dir() else core/'cloud'
if cloud.is_dir(): shutil.copytree(cloud,output/'cloud',dirs_exist_ok=True)
def version(name):
    return hashlib.sha256((output/name).read_bytes()).hexdigest()[:12]
app=(output/'app.js').read_text(encoding='utf-8-sig')
app=app.replace("'./demo.js'", "'./demo.js?v="+version('demo.js')+"'", 1)
app=app.replace("fetch('models.json'", "fetch('models.json?v="+version('models.json')+"'", 1)
(output/'app.js').write_text(app,encoding='utf-8')
html=(output/'index.html').read_text(encoding='utf-8-sig')
html=html.replace('href="style.css"','href="style.css?v='+version('style.css')+'"',1)
html=html.replace('src="app.js"','src="app.js?v='+version('app.js')+'"',1)
(output/'index.html').write_text(html,encoding='utf-8')
models=json.loads((output/'models.json').read_text(encoding='utf-8-sig'))['models']
for m in models:
    for field in ['outline','rear','atlas','atlasThumb']:
        value=m.get(field)
        if value and not value.startswith('https://'):
            assert (output/value).is_file(),f'Missing {field}: {m["id"]}'
print(f'Website ready: {len(models)} models, {len(seen)} assets')
