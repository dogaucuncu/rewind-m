"""One place that knows how to start Renode headless.

Four tools were each spelling out the same argument list. That is four places to
get `--plain` wrong and four places that would need editing when the invocation
changes.
"""

from __future__ import annotations

import pathlib
import subprocess


def run_script(renode: str, resc: pathlib.Path, timeout: int = 300):
    return subprocess.run(
        [renode, "--console", "--disable-xwt", "--plain",
         "-e", f"include @{resc.as_posix()}"],
        capture_output=True, text=True, timeout=timeout,
    )
