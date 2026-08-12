"""One place that knows how to start Renode headless.

Five tools were each spelling out the same argument list. That is five places to
get `--plain` wrong and five places that would need editing when the invocation
changes.

`TimeoutError` is raised instead of `subprocess.TimeoutExpired` so callers do not
have to import subprocess to catch it - the reason four of the five tools let a
single wedged run take the whole batch down with it.
"""

from __future__ import annotations

import pathlib
import subprocess


class RenodeTimeout(TimeoutError):
    """A Renode process had to be killed. One seed, not the whole run."""


def run_script(renode: str, resc: pathlib.Path, timeout: int = 300):
    try:
        return subprocess.run(
            [renode, "--console", "--disable-xwt", "--plain",
             "-e", f"include @{resc.as_posix()}"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenodeTimeout(
            f"renode did not finish within {timeout}s for {resc.name}"
        ) from exc
