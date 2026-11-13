#!/usr/bin/env python3
"""Report readiness without network calls or displaying credentials."""
import importlib.metadata
import json
import os
import shutil
import sys

report = {'python': sys.version.split()[0],
          'python_supported': (3, 11) <= sys.version_info[:2] < (3, 14),
          'bash': shutil.which('bash'), 'docker': shutil.which('docker'),
          'LLM_BASE_URL_set': bool(os.getenv('LLM_BASE_URL')),
          'LLM_API_KEY_set': bool(os.getenv('LLM_API_KEY'))}
try:
    report['openjiuwen'] = importlib.metadata.version('openjiuwen')
except importlib.metadata.PackageNotFoundError:
    report['openjiuwen'] = None
print(json.dumps(report, indent=2))
