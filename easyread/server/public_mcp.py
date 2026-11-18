"""Official MCP SDK, stateless Streamable HTTP, on the existing HTTP listener."""
import asyncio
from concurrent.futures import TimeoutError
from functools import wraps
import threading

from .public_api import APIError


class MCPBridge:
    def __init__(self, api):
        from mcp.server.fastmcp import FastMCP
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.types import CallToolResult, TextContent, ToolAnnotations
        import json

        # Host/Origin and access-code checks run in public_routes before dispatch.
        self.server = FastMCP("EasyRead", stateless_http=True, json_response=True,
                             instructions="Read your EasyRead library. Import tasks are asynchronous; inspect state and processing separately. File uploads use POST /api/v1/imports/file.",
                             transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
        functions = {"get_info": api.info, "list_documents": api.documents, "get_document": api.document,
                     "get_notes": api.notes, "get_highlights": api.highlights, "get_content": api.content,
                     "list_categories": api.categories, "get_document_links": api.links,
                     "import_url": api.import_url, "get_task": api.task}
        def wrap(fn):
            @wraps(fn)
            def invoke(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except APIError as exc:
                    body = exc.body()
                    return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps(body))], structuredContent=body)
            return invoke
        for name, fn in functions.items():
            self.server.add_tool(wrap(fn), name=name,
                                 description=DESCRIPTIONS[name],
                                 annotations=ToolAnnotations(readOnlyHint=name != "import_url", destructiveHint=False,
                                                             openWorldHint=name == "import_url"))
        self.asgi = self.server.streamable_http_app()
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="easyread-mcp")
        self.thread.start()
        if not self.ready.wait(10) or self.error:
            raise APIError("mcp_unavailable", "MCP initialization failed", 503)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._lifetime())
        except Exception as exc:
            self.error = exc
            self.ready.set()
        finally:
            self.loop.close()

    async def _lifetime(self):
        self.stop = asyncio.Event()
        async with self.server.session_manager.run():
            self.ready.set()
            await self.stop.wait()

    def close(self):
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.stop.set)
            self.thread.join(timeout=5)

    def dispatch(self, handler, body):
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": handler.command, "scheme": "http", "path": "/mcp", "raw_path": b"/mcp",
                 "query_string": b"", "root_path": "", "server": handler.server.server_address[:2],
                 "client": handler.client_address[:2],
                 "headers": [(k.lower().encode("latin1"), v.encode("latin1")) for k, v in handler.headers.items()]}
        future = asyncio.run_coroutine_threadsafe(self._request(scope, body), self.loop)
        try:
            status, headers, payload = future.result(timeout=60)
        except TimeoutError:
            future.cancel()
            raise APIError("mcp_timeout", "MCP request timed out", 504) from None
        handler.send_response(status)
        for key, value in headers:
            if key.lower() not in (b"content-length", b"transfer-encoding", b"connection"):
                handler.send_header(key.decode("latin1"), value.decode("latin1"))
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        if payload:
            handler.wfile.write(payload)

    async def _request(self, scope, body):
        sent = False
        status, headers, chunks = 500, [], []
        finished = asyncio.Event()
        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await finished.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            nonlocal status, headers
            if message["type"] == "http.response.start":
                status, headers = message["status"], message.get("headers", [])
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if not message.get("more_body"):
                    finished.set()
        await self.asgi(scope, receive, send)
        return status, headers, b"".join(chunks)


DESCRIPTIONS = {
    "get_info": "Get service version, capabilities, limits and access-protection status.",
    "list_documents": "Search document metadata. Filter by category (includes descendants) and reading status. Paginate with limit/offset.",
    "get_document": "Get document metadata, progress, current processing job and reading links.",
    "get_notes": "Read paper-wide and paragraph notes/questions. Excludes deleted notes and highlight-only entries.",
    "get_highlights": "Read highlight entries with quote, color, anchor and source links.",
    "get_content": "Read ordered content blocks: language=original|translation|both, view=effective (user edits) or raw. Historical en/zh keys mean original/target language. Paginate using limit/offset.",
    "list_categories": "List category tree as ordered paths with parent and document count, including empty categories.",
    "get_document_links": "Get web and easyread:// links, optionally anchored to a block ID.",
    "import_url": "Queue a public HTTP(S) PDF, article or arXiv URL. translate defaults to false; true may invoke paid models. No private addresses or JavaScript execution. Returns task_id.",
    "get_task": "Get durable import task status. state=done means import complete, NOT translation complete; processing reports the document's current preparation/translation state and progress.",
}
