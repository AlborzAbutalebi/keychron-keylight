"""Keylight.app entry point: runs the engine + local server in a background thread and shows the UI
in a native macOS window (WKWebView via pywebview). Closing the window quits the app, and the keyboard
returns to its own (saved) lighting."""
import asyncio
import os
import sys
import threading

import webview

import keylight


def _keep_awake():
    """Stop App Nap from throttling the render loop while the window is hidden or minimised."""
    try:
        from Foundation import NSActivityUserInitiatedAllowingIdleSystemSleep, NSProcessInfo

        return NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
            NSActivityUserInitiatedAllowingIdleSystemSleep, "Streaming keyboard lighting")
    except Exception:
        return None


def main():
    port = keylight.pick_port(8787)
    ready = threading.Event()
    loop = asyncio.new_event_loop()

    def run_server():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(keylight.serve(port, on_ready=lambda _: ready.set()))
        except asyncio.CancelledError:
            pass

    threading.Thread(target=run_server, daemon=True).start()
    if not ready.wait(15):
        sys.exit("Keylight server failed to start")

    activity = _keep_awake()  # noqa: F841 (must stay referenced)
    webview.create_window("Keylight", f"http://127.0.0.1:{port}/", width=1240, height=900,
                          min_size=(760, 600), background_color="#0b0c10")
    webview.start()

    # Window closed: stop streaming so the keyboard takes its lighting back immediately.
    def shutdown():
        for task in asyncio.all_tasks(loop):
            task.cancel()

    loop.call_soon_threadsafe(shutdown)
    threading.Event().wait(0.5)
    os._exit(0)


if __name__ == "__main__":
    main()
