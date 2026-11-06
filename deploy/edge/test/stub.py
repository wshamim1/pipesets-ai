# Stand-in backend / frontend for test.sh: answers every request with who it is, the path and
# the forwarded headers it got.
import http.server, os, sys
NAME = os.environ["NAME"]
class H(http.server.BaseHTTPRequestHandler):
    def _r(self):
        body = f"{NAME} {self.command} {self.path} xff={self.headers.get('X-Forwarded-For')} proto={self.headers.get('X-Forwarded-Proto')}\n".encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    do_GET = do_POST = _r
    def log_message(self, *a): pass
http.server.HTTPServer(("0.0.0.0", int(sys.argv[1])), H).serve_forever()
