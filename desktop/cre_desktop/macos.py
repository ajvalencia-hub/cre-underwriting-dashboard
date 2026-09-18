"""macOS-specific hooks.

Cmd+Q goes through NSApplication terminate:, which calls exit() without
returning from pywebview's event loop — so the launcher's normal shutdown
path after webview.start() never runs. Observing the will-terminate
notification lets the same shutdown run on that path too.
"""

from typing import Callable

import AppKit
import Foundation


class _TerminateObserver(Foundation.NSObject):
    def initWithCallback_(self, callback):
        self = self.init()
        if self is None:
            return None
        self._callback = callback
        return self

    def appWillTerminate_(self, _notification):
        self._callback()


_observer = None  # keep a strong reference for the life of the process


def on_app_will_terminate(callback: Callable[[], None]) -> None:
    global _observer
    _observer = _TerminateObserver.alloc().initWithCallback_(callback)
    Foundation.NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        _observer,
        "appWillTerminate:",
        AppKit.NSApplicationWillTerminateNotification,
        None,
    )
