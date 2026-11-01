"""Run manifest: every file in this run directory with its sha256."""
import hashlib
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    files = []
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.pytest_cache')]
        for n in sorted(names):
            p = os.path.join(base, n)
            rel = os.path.relpath(p, ROOT)
            if rel.endswith('run_manifest.json'):
                continue
            files.append({'path': rel, 'bytes': os.path.getsize(p),
                          'sha256': sha256(p)})
    manifest = {
        'run_dir': ROOT,
        'generated_at': subprocess.run(['date', '-Is'], capture_output=True,
                                       text=True).stdout.strip(),
        'file_count': len(files),
        'files': files,
    }
    with open(os.path.join(ROOT, 'outputs', 'run_manifest.json'), 'w') as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    print('manifest:', len(files), 'files')


if __name__ == '__main__':
    main()
