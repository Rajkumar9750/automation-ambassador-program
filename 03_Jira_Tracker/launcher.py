#!/usr/bin/env python3
"""
Jira Tracker — macOS menu bar launcher.
Click the menu bar icon to start/stop the server and open the browser.
"""
import os
import signal
import subprocess
import webbrowser

import rumps

PORT = 8082
URL = f"http://localhost:{PORT}"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UVICORN = os.path.join(BASE_DIR, "venv", "bin", "uvicorn")


def _server_pid() -> int | None:
    """Return PID of the uvicorn process listening on PORT, or None."""
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{PORT}"], text=True
        ).strip()
        return int(out.split()[0]) if out else None
    except subprocess.CalledProcessError:
        return None


class JiraTrackerApp(rumps.App):
    def __init__(self):
        super().__init__("Jira", quit_button=None)
        self._proc: subprocess.Popen | None = None

        self.btn_toggle = rumps.MenuItem("Start Server", callback=self.toggle)
        self.btn_open   = rumps.MenuItem("Open in Browser", callback=self.open_browser)
        self.btn_quit   = rumps.MenuItem("Quit", callback=self.quit_app)

        self.menu = [self.btn_toggle, self.btn_open, None, self.btn_quit]
        self._sync_ui()

    # ------------------------------------------------------------------ helpers

    def _is_running(self) -> bool:
        if self._proc and self._proc.poll() is None:
            return True
        return _server_pid() is not None

    def _sync_ui(self):
        running = self._is_running()
        self.title = "● Jira" if running else "○ Jira"
        self.btn_toggle.title = "Stop Server" if running else "Start Server"
        self.btn_open.set_callback(self.open_browser if running else None)

    # ------------------------------------------------------------------ actions

    def toggle(self, _):
        if self._is_running():
            self._stop()
        else:
            self._start()
        self._sync_ui()

    def _start(self):
        self._proc = subprocess.Popen(
            [
                UVICORN,
                "jira_tracker:app",
                "--host", "0.0.0.0",
                "--port", str(PORT),
            ],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait briefly then open browser
        import time; time.sleep(1.5)
        if self._is_running():
            webbrowser.open(URL)
            rumps.notification("Jira Tracker", "Server started", URL)

    def _stop(self):
        pid = _server_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if self._proc:
            self._proc.terminate()
            self._proc = None
        rumps.notification("Jira Tracker", "Server stopped", "")

    def open_browser(self, _):
        webbrowser.open(URL)

    def quit_app(self, _):
        if self._is_running():
            self._stop()
        rumps.quit_application()

    # ------------------------------------------------------------------ timer

    @rumps.timer(5)
    def refresh(self, _):
        self._sync_ui()


if __name__ == "__main__":
    JiraTrackerApp().run()
