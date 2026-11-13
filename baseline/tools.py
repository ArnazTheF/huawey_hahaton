import os
import selectors
import signal
import subprocess
import time
from pathlib import Path


def run_command(command, cwd, timeout, max_output=12000):
    # Do not pass API credentials or host-specific environment to generated code.
    env = {'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'),
           'HOME': str(cwd), 'TMPDIR': str(cwd), 'LANG': 'C.UTF-8',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8'}
    started = time.monotonic()
    proc = subprocess.Popen(['/bin/bash', '-c', command], cwd=cwd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)
    captured = bytearray()
    total = 0
    timed_out = False
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            if time.monotonic() - started >= timeout:
                timed_out = True
                break
            for key, _ in selector.select(timeout=min(0.1, timeout)):
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                captured.extend(chunk[:max(0, max_output - len(captured))])
        if proc.poll() is None:
            try:
                proc.wait(timeout=max(0.01, timeout - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        # Also clean up descendants that outlive their parent shell.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        selector.close()
        proc.stdout.close()
    return {'returncode': proc.returncode, 'timeout': timed_out,
            'output': captured.decode('utf-8', errors='replace'),
            'truncated': total > max_output}


def safe_path(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Path must stay inside the task workspace')
    return path


def execute(action, root, timeout, max_output):
    kind = action.get('action')
    if kind == 'bash':
        return run_command(action['command'], root, timeout, max_output)
    if kind == 'read':
        path = safe_path(root, action['path'])
        with path.open('rb') as source:
            data = source.read(max_output + 1)
        return {'content': data[:max_output].decode('utf-8', errors='replace'),
                'truncated': len(data) > max_output}
    if kind == 'write':
        path = safe_path(root, action['path'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(action['content'], encoding='utf-8')
        return {'written': action['path']}
    if kind == 'edit':
        path=safe_path(root,action['path'])
        if path.name.startswith('test') and path.suffix=='.py':
            raise ValueError('Tests are immutable')
        if not action['old'] or action['old']==action['new']:
            raise ValueError('edit requires nonempty old text and a material change')
        if path.stat().st_size>8*1024*1024:
            raise ValueError('edit file exceeds 8 MiB')
        content=path.read_bytes().decode('utf-8')
        offset=content.find(action['old'])
        if offset<0 or content.find(action['old'],offset+1)>=0:
            raise ValueError('edit.old must match exactly once; file unchanged')
        replacement=content[:offset]+action['new']+content[offset+len(action['old']):]
        from .core import atomic_write
        mode=path.stat().st_mode & 0o777
        atomic_write(path,replacement)
        path.chmod(mode)
        return {'edited':action['path'],'replacements':1}
    raise ValueError('Unknown action')
