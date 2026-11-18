"""Prepare a fresh local sample for the folder upload/download video segment."""
import hashlib
import os
import shlex
from datetime import datetime
from pathlib import Path
from uuid import uuid4

project = Path(__file__).resolve().parents[1]
stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:4]
root = project / 'runtime' / ('folder-demo-' + stamp)
source = root / '上传源'
destination = root / '下载结果'
source.mkdir(parents=True, exist_ok=False)
destination.mkdir()
file = source / '完整性样例.bin'
digest = hashlib.sha256()
with file.open('xb') as stream:
    for _ in range(8):
        chunk = os.urandom(1024 * 1024)
        stream.write(chunk)
        digest.update(chunk)
remote = '文件夹演示-' + stamp
values = {'FOLDER_DEMO_ROOT': str(root), 'REMOTE_DEMO_DIR': remote, 'DEMO_SHA256': digest.hexdigest()}
env = project / 'runtime' / 'folder-demo.env'
env.write_text(''.join(f'export {key}={shlex.quote(value)}\n' for key, value in values.items()))
(root / '样例说明.txt').write_text(
    f'本地源：上传源/完整性样例.bin\n大小：8388608 字节（8 MiB）\n'
    f'远端文件夹：{remote}\n下载位置：下载结果/{remote}/完整性样例.bin\n'
    f'源文件 SHA-256：{digest.hexdigest()}\n', encoding='utf-8')
print('本地选择目录：', root)
print('远端新建文件夹：', remote)
print('源文件大小：', file.stat().st_size, '字节')
print('源文件 SHA-256：', digest.hexdigest())
print('在本机终端执行 . runtime/folder-demo.env 可载入本次路径。')
