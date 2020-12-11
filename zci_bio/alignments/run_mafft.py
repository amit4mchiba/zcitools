#!/usr/bin/python3

import os.path
from concurrent.futures import ThreadPoolExecutor
try:                 # Run locally, with whole project
    import common_utils.run_utils as run_utils
except ImportError:  # Run standalone, on server
    import run_utils

_DEFAULT_EXE_NAME = 'mafft'
_ENV_VAR = 'MAFFT_EXE'

# From my observations ...
#
# Calculation strategy:
#  - First run short sequences on one thread. Sort them from longer (short) to shorter.
#  - Than run long sequences sequential

_install_instructions = """
MAFFT is not installed!
Check web page https://mafft.cbrc.jp/alignment/software/ for installation instructions.

There are two ways for this script to locate executable to run:
 - environment variable {env_var} points to executable location,
 - or executable is called {exe} and placed on the PATH.
"""


def _alignment_file(f):
    return os.path.join(os.path.dirname(f), 'alignment.phy')


def _run_single(mafft_exe, filename, namelength, output_file, threads):
    run_utils.run_cmd([mafft_exe, '--maxiterate', 10, '--phylipout', '--namelength', max(10, namelength),
                       '--thread', threads, filename], output_file=output_file)


def run(locale=True, threads=None):
    # Note: run from step's directory!!!
    mafft_exe = run_utils.find_exe(_DEFAULT_EXE_NAME, _ENV_VAR, _install_instructions, 'MAFFT')
    threads = threads or run_utils.get_num_threads()
    log_run = run_utils.LogRun(threads=threads)
    outputs = []

    # Files to run
    seq_files = run_utils.load_finish_yml()  # dict with attrs: filename, short, max_seq_length
    short_files = sorted((d for d in seq_files if d['short']), key=lambda x: -x['max_seq_length'])
    long_files = sorted((d for d in seq_files if not d['short']), key=lambda x: x['max_seq_length'])

    if short_files:
        with ThreadPoolExecutor(max_workers=threads) as executor:
            for d in short_files:
                outputs.append(_alignment_file(d['filename']))
                executor.submit(_run_single, mafft_exe, d['filename'], d['namelength'], outputs[-1], 1)

    for d in long_files:
        outputs.append(_alignment_file(d['filename']))
        _run_single(mafft_exe, d['filename'], d['namelength'], outputs[-1], threads)

    # Zip files
    if not locale:
        run_utils.zip_files(outputs)

    #
    log_run.finish()


if __name__ == '__main__':
    import sys
    run(locale=False, threads=int(sys.argv[1]) if len(sys.argv) > 1 else None)
