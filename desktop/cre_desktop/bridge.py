"""Python functions exposed to the web UI as window.pywebview.api.*

Every public method here is callable from JavaScript, so keep the surface
small and validate inputs.
"""

import logging
import subprocess

log = logging.getLogger(__name__)


class DesktopBridge:
    def __init__(self, paths):
        # Leading underscore: pywebview doesn't expose private attributes.
        self._paths = paths
        self._window = None
        self.restart_requested = False

    def attach(self, window) -> None:
        self._window = window

    def reveal_logs(self) -> None:
        subprocess.run(["/usr/bin/open", "-R", str(self._paths.log_file)], check=False)
