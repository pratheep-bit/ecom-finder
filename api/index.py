import sys
import urllib.parse
from pathlib import Path
from starlette.types import ASGIApp, Scope, Receive, Send

# Add project root directory to sys.path so 'backend' package is importable in Vercel Serverless environment
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from backend.app.main import app as fastapi_app

class VercelPathFixMiddleware:
    def __init__(self, asgi_app: ASGIApp):
        self.asgi_app = asgi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope.get("type") in ("http", "websocket"):
            query_string = scope.get("query_string", b"").decode("utf-8")
            parsed_query = urllib.parse.parse_qs(query_string)
            if "__vpath" in parsed_query:
                raw_path = parsed_query.pop("__vpath")[0]
                new_query = urllib.parse.urlencode([(k, v) for k, vs in parsed_query.items() for v in vs])
                scope["query_string"] = new_query.encode("utf-8")
                clean_path = raw_path.strip("/")
                scope["path"] = f"/api/{clean_path}" if clean_path else "/api"
        await self.asgi_app(scope, receive, send)

app = VercelPathFixMiddleware(fastapi_app)
