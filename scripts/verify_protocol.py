"""Reproduce finite-state SFT1 model checks; requires Java 11+ and Python 3.9+."""
import hashlib
import json
import platform
import re
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMAL = ROOT / 'formal'
JAR = FORMAL / 'tools/tla2tools.jar'
URL = 'https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar'
SHA1 = 'bee4a54f3ee3d4afc347c3240ec2d9e93b075104'

def run():
    JAR.parent.mkdir(parents=True, exist_ok=True)
    if not JAR.exists():
        urllib.request.urlretrieve(URL, JAR)
    raw = JAR.read_bytes()
    if hashlib.sha1(raw).hexdigest() != SHA1:
        raise SystemExit('TLC JAR does not match upstream v1.7.4 checksum')
    result_dir = FORMAL / 'results'
    result_dir.mkdir(exist_ok=True)
    results = []
    for cfg in sorted(FORMAL.glob('*.cfg')):
        module = 'SFT1Upload' if cfg.stem.startswith('upload') else 'SFT1Download'
        expected = ('Invariant NoCompletion is violated' if cfg.stem.endswith('completion_witness') else 'Temporal properties were violated' if cfg.stem.endswith('unfair') else
            {'early_ack':'Invariant AckDurable is violated',
             'early_finish':'Invariant PublishedIntegrity is violated',
             'duplicate_append':'Invariant Bounds is violated',
             'no_owner':'Invariant Isolation is violated',
             'resume':'Invariant ResumeIdentity is violated'}.get(cfg.stem.split('mutant_')[-1])
             if 'mutant_' in cfg.stem else None)
        with tempfile.TemporaryDirectory(prefix='sft1-tlc-') as meta:
            cmd = ['java', '-XX:+UseParallelGC', '-Xmx1g', '-cp', str(JAR), 'tlc2.TLC',
                '-workers', '1', '-seed', '1', '-fp', '0',
                '-config', cfg.name, '-metadir', meta, module+'.tla']
            proc = subprocess.run(cmd, cwd=FORMAL, capture_output=True, text=True, timeout=180)
        log = proc.stdout + proc.stderr
        (result_dir/(cfg.stem+'.log')).write_text(log)
        counts = re.findall(r'([\d,]+) states generated, ([\d,]+) distinct states found', log)
        depth = re.search(r'depth of the complete state graph search is (\d+)', log)
        passed = (proc.returncode == 0 and 'Model checking completed. No error has been found.' in log) if expected is None else (expected in log and proc.returncode != 0)
        row = dict(case=cfg.stem, module=module, expected=expected or 'no_error',
            exit_code=proc.returncode, expectation_met=passed,
            generated=int(counts[-1][0].replace(',','')) if counts else None,
            distinct=int(counts[-1][1].replace(',','')) if counts else None,
            depth=int(depth[1]) if depth else None,
            command=['java','-XX:+UseParallelGC','-Xmx1g','-cp','tools/tla2tools.jar',
                     'tlc2.TLC','-workers','1','-seed','1','-fp','0',
                     '-config',cfg.name,module+'.tla'])
        results.append(row)
        print(f"{cfg.stem}: {'OK' if passed else 'UNEXPECTED'} states={row['distinct']} exit={proc.returncode}", flush=True)
    tracked = [*FORMAL.glob('*.tla'), *FORMAL.glob('*.cfg'), ROOT/'docs/protocol.md',
        ROOT/'server/ex1b/server.py', ROOT/'server/ex1b/storage.py', ROOT/'server/ex1b/database.py',
        ROOT/'macos/Sources/SafeTransferCore/TransferEngine.swift',
        ROOT/'macos/Sources/SafeTransferCore/Disk.swift',
        ROOT/'macos/Sources/SafeTransferCore/TaskStore.swift',
        *sorted((ROOT/'tests').glob('test_*.py')), Path(__file__).resolve()]
    report = dict(time=datetime.now(timezone.utc).isoformat(), platform=platform.platform(),
        java=subprocess.run(['java','-version'],capture_output=True,text=True).stderr.strip(),
        tool_url=URL, jar_sha256=hashlib.sha256(raw).hexdigest(),
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        files_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked},
        results=results)
    (result_dir/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    if not all(r['expectation_met'] for r in results):
        raise SystemExit('Unexpected TLC results; inspect formal/results/*.log')

if __name__ == '__main__':
    run()
