"""HTTP helpers using only the standard library.

A CA bundle is shipped next to this file so HTTPS works even on a portable
Python runtime that cannot see the operating system's certificate store.
"""
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_CTX = None


def ssl_context():
    global _CTX
    if _CTX is None:
        ctx = ssl.create_default_context()
        try:
            ctx.load_default_certs()
        except Exception:
            pass
        bundle = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cacert.pem")
        if os.path.exists(bundle):
            ctx.load_verify_locations(cafile=bundle)
        _CTX = ctx
    return _CTX


class FetchError(Exception):
    pass


def fetch(url, timeout=30, retries=2, headers=None, data=None, method=None):
    """Return response body as bytes. Retries on network errors and 5xx/429."""
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs, data=data, method=method)
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()[:500]
            except Exception:
                pass
            last = FetchError("HTTP %s: %s" % (e.code, body.decode("utf-8", "replace")))
            if e.code not in (429, 500, 502, 503, 504):
                break
        except urllib.error.URLError as e:
            last = FetchError("Không kết nối được (%s)" % (e.reason,))
            if isinstance(e.reason, (ConnectionRefusedError, socket.gaierror, OSError)) and \
                    not isinstance(e.reason, socket.timeout):
                break  # offline / DNS failure: retrying will not help
        except Exception as e:  # timeout, ssl errors
            last = FetchError("%s: %s" % (type(e).__name__, e))
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise last


def fetch_json(url, **kw):
    raw = fetch(url, **kw)
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        raise FetchError("Phản hồi không phải JSON (có thể bị chặn): %r" % raw[:120])


def post_json(url, payload, headers=None, timeout=90):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    return fetch_json(url, data=json.dumps(payload).encode("utf-8"), headers=h,
                      timeout=timeout, retries=1, method="POST")
