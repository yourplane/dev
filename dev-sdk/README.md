# dev-sdk

Business logic for the dev CLI: task lifecycle, comms, agent flows, and PR creation. Used by the `dev` CLI and intended for reuse by a future server and web UI.

## Debugging

The SDK logs at **DEBUG** level around blocking operations (agent chat creation, git clone, branch checkout, venv/pip setup) so you can see where execution is when things hang. The logger name is `dev_sdk`.

- **Default:** When the dev CLI is run with `--debug` (or `DEV_DEBUG=1`), it sets the `dev_sdk` logger to DEBUG and adds a **file handler** so all SDK debug logs go to a log file (not stdout). The log file path is `~/.local/share/dev/sdk-debug.log` (or the path given by `DEV_SDK_LOG`).
- **From your own code:** To enable SDK debug logs to a file, configure the logger before using the SDK:

  ```python
  import logging
  logging.getLogger("dev_sdk").setLevel(logging.DEBUG)
  handler = logging.FileHandler("/path/to/sdk-debug.log", encoding="utf-8")
  handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
  logging.getLogger("dev_sdk").addHandler(handler)
  ```

The last log line before a hang indicates which operation is stuck.
