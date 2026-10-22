import argparse,hashlib,json,shutil,urllib.request,zipfile
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--source',default='.')
parser.add_argument('--output',default='_site')
parser.add_argument('--archive')
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
for name in ['index.html','style.css','app.js','demo.js','models.json','.nojekyll']:
    shutil.copyfile(core/name,output/name)
cloud=source/'cloud' if (source/'cloud').is_dir() else core/'cloud'
if cloud.is_dir(): shutil.copytree(cloud,output/'cloud',dirs_exist_ok=True)
models=json.loads((output/'models.json').read_text(encoding='utf-8-sig'))['models']
for m in models:
    for field in ['outline','rear','atlas','atlasThumb']:
        value=m.get(field)
        if value and not value.startswith('https://'):
            assert (output/value).is_file(),f'Missing {field}: {m["id"]}'
print(f'Website ready: {len(models)} models, {len(seen)} assets')
