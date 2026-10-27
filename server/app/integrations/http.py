"""HTTP transport shared by external adapters; never log credential-bearing requests."""
import logging

import httpx


def client(timeout=30):
    # httpx INFO logs include Bot API tokens in URLs; httpcore DEBUG includes headers.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)
