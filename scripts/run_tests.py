"""Run unit tests and expose failures in GitHub check annotations."""
import os
import subprocess
import sys

result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
print(result.stdout, end='')
if result.returncode and os.environ.get('GITHUB_ACTIONS'):
    text = result.stdout[-4000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    print(f'::error title=Unit tests failed::{text}')
sys.exit(result.returncode)
