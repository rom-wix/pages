"""Minimal MCP (Streamable HTTP) client for the market-data server.

Credentials come from the environment only (never commit them):
  MCP_URL, MCP_TOKEN, MCP_UA (a full Chrome User-Agent string; the server sits behind Cloudflare)

  python3 scripts/mcp_client.py tools                      # list tools and their input schemas
  python3 scripts/mcp_client.py call <tool> '<json args>'  # call a tool, print the result
"""
from __future__ import annotations

import json
import os
import sys

import requests


class MCP:
    def __init__(self, url=None, token=None, ua=None, timeout=120):
        self.url = url or os.environ["MCP_URL"]
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token or os.environ['MCP_TOKEN']}",
            "User-Agent": ua or os.environ["MCP_UA"],
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })
        self.timeout = timeout
        self.sid = None
        self._id = 0
        self._init()

    def _post(self, payload, expect_reply=True):
        h = {"Mcp-Session-Id": self.sid} if self.sid else {}
        r = self.s.post(self.url, data=json.dumps(payload), headers=h, timeout=self.timeout)
        if "mcp-session-id" in r.headers:
            self.sid = r.headers["mcp-session-id"]
        r.raise_for_status()
        if not expect_reply:
            return None
        ctype = r.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            msg = None
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    d = json.loads(line[5:].strip())
                    if d.get("id") == payload.get("id"):
                        msg = d
            return msg
        return r.json() if r.text.strip() else None

    def rpc(self, method, params=None):
        self._id += 1
        msg = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        if msg is None:
            raise RuntimeError(f"no reply to {method}")
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg["result"]

    def _init(self):
        self.info = self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                            "clientInfo": {"name": "oil-research", "version": "0.1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)

    def tools(self):
        out, cursor = [], None
        while True:
            res = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            out += res.get("tools", [])
            cursor = res.get("nextCursor")
            if not cursor:
                return out

    def call(self, name, args=None):
        res = self.rpc("tools/call", {"name": name, "arguments": args or {}})
        if res.get("isError"):
            raise RuntimeError(f"{name} error: {res}")
        if "structuredContent" in res:
            return res["structuredContent"]
        texts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
        joined = "\n".join(texts)
        try:
            return json.loads(joined)
        except Exception:
            return joined


if __name__ == "__main__":
    m = MCP()
    if len(sys.argv) < 2 or sys.argv[1] == "tools":
        print(json.dumps(m.info.get("serverInfo", {}), indent=1))
        for t in m.tools():
            print("\n#", t["name"], "-", (t.get("description") or "")[:300])
            print(json.dumps(t.get("inputSchema", {}), indent=1)[:1500])
    elif sys.argv[1] == "call":
        res = m.call(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {})
        s = json.dumps(res, indent=1) if not isinstance(res, str) else res
        print(s[:20000])
