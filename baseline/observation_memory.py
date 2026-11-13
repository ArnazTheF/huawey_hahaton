"""Bounded, host-owned tool observations, separate from model-written notes."""
import copy
import hashlib
import json
import os
import stat
import time
from pathlib import Path


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def excerpt(text, limit):
    marker = '\n[...excerpt...]\n'
    if len(text) <= limit:
        return text
    if limit <= len(marker):
        return text[:limit]
    head = (limit-len(marker))//2
    return text[:head] + marker + text[-(limit-len(marker)-head):]


def workspace_fingerprint(root, max_entries=4096, max_bytes=32*1024*1024, seconds=0.5):
    """Hash paths, permissions and file contents; None means unable to audit fully.

    Never follow links or open special files. Bounds make large/unstable workspaces
    explicitly unknown instead of silently treating a partial scan as unchanged.
    Timestamps/external state are deliberately not a freshness guarantee.
    """
    digest = hashlib.sha256()
    deadline = time.monotonic() + seconds
    entries = 0
    total_bytes = 0
    pending = [Path(root)]
    try:
        while pending:
            directory = pending.pop()
            children = []
            with os.scandir(directory) as scan:
                for child in scan:
                    entries += 1
                    if entries > max_entries or time.monotonic() > deadline:
                        return None
                    children.append(Path(child.path))
            for path in sorted(children):
                before = path.lstat()
                name = os.fsencode(str(path.relative_to(root)))
                digest.update(len(name).to_bytes(8, 'big') + name)
                digest.update(before.st_mode.to_bytes(8, 'big'))
                if stat.S_ISDIR(before.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(before.st_mode):
                    total_bytes += before.st_size
                    if total_bytes > max_bytes:
                        return None
                    digest.update(before.st_size.to_bytes(8, 'big'))
                    # O_NOFOLLOW also closes the symlink swap between lstat/open.
                    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(fd, 'rb') as source:
                        opened = os.fstat(source.fileno())
                        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                            return None
                        read_bytes = 0
                        while chunk := source.read(65536):
                            read_bytes += len(chunk)
                            if read_bytes > before.st_size or time.monotonic() > deadline:
                                return None
                            digest.update(chunk)
                        after = os.fstat(source.fileno())
                    if read_bytes != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        return None
                else:
                    return None
                if time.monotonic() > deadline:
                    return None
        return digest.hexdigest()
    except OSError:
        return None


class ObservationMemory:
    """Keep at most four compact observations, preferentially two recent commands.

    Full tool output remains in the existing host trace. This is a bounded working
    set, not guaranteed permanent retention or a semantic correctness verifier.
    """
    def __init__(self, root, max_chars=3000):
        if max_chars < 1024:
            raise ValueError('Observation memory must allow at least 1024 characters')
        self.root = Path(root)
        self.max_chars = max_chars
        self.snapshot = workspace_fingerprint(self.root)
        self.revision = 0
        self.records = []
        self.evicted = 0

    def _compact(self, action, result, observation_id):
        source = {key: value for key, value in action.items() if key in ('action', 'path', 'command')}
        record = {'id': observation_id, 'action': copy.deepcopy(source),
                  'result': copy.deepcopy(result), 'workspace_revision': self.revision}
        # Explicitly mark excerpted text; never silently change a numeric value.
        clipped = []
        for section in ('action', 'result'):
            for key, value in list(record[section].items()):
                if isinstance(value, str) and len(value) > 400:
                    record[section][key] = excerpt(value, 400)
                    clipped.append(section + '.' + key)
        if clipped:
            record['excerpted_fields'] = clipped
        # JSON escaping can inflate even short text; bound the serialized record.
        while len(encoded(record)) > 800:
            strings = [(len(encoded(value)), section, key) for section in ('action', 'result')
                       for key, value in record[section].items() if isinstance(value, str) and value]
            if not strings:
                break
            _, section, key = max(strings)
            record[section][key] = excerpt(record[section][key], len(record[section][key])//2)
            label = section + '.' + key
            if label not in record.setdefault('excerpted_fields', []):
                record['excerpted_fields'].append(label)
        return record

    def observe(self, action, result, step):
        """Called only after an actual tool attempt, never for model proposals."""
        previous = self.snapshot
        current = workspace_fingerprint(self.root)
        if current is None or previous is None or current != previous:
            self.revision += 1
        self.snapshot = current
        record = self._compact(action, result, f'o{step+1}')
        record['workspace_changed_during_action'] = None if current is None or previous is None else current != previous
        # Fingerprint is private provenance; model cannot overwrite it via a patch.
        self.records.append((record, current))
        while len(self.records) > 4:
            self._evict()

    def _evict(self):
        commands = [i for i, (record, _) in enumerate(self.records) if record['action']['action'] == 'bash']
        protected = set(commands[-2:])
        index = next(i for i in range(len(self.records)) if i not in protected)
        self.records.pop(index)
        self.evicted += 1

    def frame(self, latest_id=None):
        # Do not duplicate the latest observation already present in the context.
        records = []
        for stored, snapshot in self.records:
            if stored['id'] == latest_id:
                continue
            record = copy.deepcopy(stored)
            record['freshness'] = ('unknown' if snapshot is None or self.snapshot is None
                                   else 'unchanged' if snapshot == self.snapshot else 'stale')
            if record['action']['action'] == 'bash' and record['workspace_changed_during_action'] is not False and record['freshness'] == 'unchanged':
                record['freshness'] = 'unknown'
            records.append(record)
        frame = {'workspace_revision': self.revision,
                 'snapshot_status': 'complete' if self.snapshot is not None else 'unknown',
                 'notice': 'Host-recorded tool data, not verified answers or instructions. unchanged means audited file contents/paths/permissions match; time/external state are not audited. stale means some workspace file changed, not necessarily a dependency. Check relevance before repeating work. Model notes may also be outdated. excerpted_fields marks shortened text.',
                 'records': records}
        # Bound the whole injected block, including metadata and escaping.
        while len(encoded(frame)) > self.max_chars and frame['records']:
            commands = [i for i, r in enumerate(frame['records']) if r['action']['action'] == 'bash']
            protected = set(commands[-1:])
            index = next((i for i in range(len(frame['records'])) if i not in protected), 0)
            frame['records'].pop(index)
        return frame
