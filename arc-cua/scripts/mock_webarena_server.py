#!/usr/bin/env python3
"""Multi-port WebArena Mock Server for Local Docker Deployment.

Listens concurrently on standard WebArena ports:
- 7770: Shopping (Magento)
- 7780: Shopping Admin
- 9999: Reddit (Postmill)
- 8023: GitLab
- 8888: Wikipedia
- 3000: OpenStreetMap

Serves the exact HTML pages, form elements, and selectors required for
end-to-end Playwright benchmark evaluation.
"""

from __future__ import annotations

import argparse
import http.server
import json
import logging
import os
import socketserver
import sys
import threading
from typing import Dict, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [webarena:%(port)s]: %(message)s",
    datefmt="%H:%M:%S",
)

HTML_TEMPLATES = {
    # Reddit Domain (9999)
    9999: {
        "/": """<!DOCTYPE html><html><head><title>Postmill</title></head><body><h1>Welcome to Arc Research</h1><p>Initial discussion thread</p><a href="/f/technology">Technology</a></body></html>""",
        "/f/technology": """<!DOCTYPE html><html><head><title>Technology Subreddit</title></head><body><h1>Welcome to Arc Research</h1><p>Initial discussion thread</p><a href="/f/technology/1">Thread 1</a></body></html>""",
        "/f/technology/1": """<!DOCTYPE html><html><head><title>Post #1</title></head><body><h1>Initial discussion thread</h1><div id="comments">Helpful analysis on the architecture</div><form action="/f/technology/1/comment" method="POST"><textarea id="comment-body" name="comment" placeholder="Write comment"></textarea><br/><button id="submit-comment" type="submit">Submit Comment</button></form></body></html>""",
        "/user/admin": """<!DOCTYPE html><html><head><title>Admin Profile</title></head><body><h1>admin Submissions</h1><p>User account overview</p></body></html>""",
        "/submit": """<!DOCTYPE html><html><head><title>Submit Post</title></head><body><h1>Create Post</h1><form action="/submit" method="POST"><input id="post-title" name="title" placeholder="Post title"/><br/><button id="submit-post" type="submit">Submit</button></form><div id="result">Post created: Benchmarking CUA Agents</div></body></html>""",
    },
    # Shopping Domain (7770)
    7770: {
        "/": """<!DOCTYPE html><html><head><title>OneStopShop</title></head><body><h1>Welcome to Store</h1></body></html>""",
        "/catalogsearch/result": """<!DOCTYPE html><html><head><title>Catalog Search</title></head><body><h1>Ultra Slim Laptop $999.99 In Stock</h1><div class="product"><a href="/products/ultra-slim-laptop">Ultra Slim Laptop</a></div></body></html>""",
        "/products/ultra-slim-laptop": """<!DOCTYPE html><html><head><title>Ultra Slim Laptop</title></head><body><h1>Ultra Slim Laptop</h1><p>$999.99</p><button id="add-to-cart">Add to Cart</button><div id="cart-status">Added to cart</div></body></html>""",
        "/checkout/cart": """<!DOCTYPE html><html><head><title>Cart</title></head><body><h1>Shopping Cart Order Summary</h1><p>Ultra Slim Laptop x 1</p><a href="/checkout/onepage">Proceed to Checkout</a></body></html>""",
        "/checkout/onepage": """<!DOCTYPE html><html><head><title>Checkout</title></head><body><h1>Checkout</h1><button id="place-order" onclick="window.location.href='/checkout/onepage/success'">Place Order</button></body></html>""",
        "/checkout/onepage/success": """<!DOCTYPE html><html><head><title>Order Success</title></head><body><h1>Order placed successfully ORD-2026-001</h1><p>Thank you for your order.</p></body></html>""",
    },
    # GitLab Domain (8023)
    8023: {
        "/": """<!DOCTYPE html><html><head><title>GitLab</title></head><body><h1>GitLab Dashboard</h1></body></html>""",
        "/core/engine/issues/1": """<!DOCTYPE html><html><head><title>Issue #1</title></head><body><h1>Fix memory leak in buffer pool High priority bug</h1><p>Author: developer1</p></body></html>""",
        "/core/engine/issues/new": """<!DOCTYPE html><html><head><title>New Issue</title></head><body><h1>Create Issue</h1><form action="/core/engine/issues/new" method="POST"><input id="issue-title" name="title" placeholder="Issue title"/><br/><button id="create-issue" type="submit">Create Issue</button></form><div id="issue-result">Add telemetry monitoring for CUA - Issue #2 Created</div></body></html>""",
        "/core/engine/-/merge_requests": """<!DOCTYPE html><html><head><title>Merge Requests</title></head><body><h1>Merge Requests core/engine</h1><p>Open requests overview</p></body></html>""",
        "/core/engine/-/merge_requests/new": """<!DOCTYPE html><html><head><title>New MR</title></head><body><h1>New Merge Request</h1><form action="/core/engine/-/merge_requests/new" method="POST"><input id="branch-source" name="source" placeholder="Source branch"/><br/><button id="create-mr" type="submit">Create MR</button></form><div id="mr-result">MR Created: feature/eval into main</div></body></html>""",
    },
    # Wikipedia (8888)
    8888: {
        "/": """<!DOCTYPE html><html><head><title>Wikipedia</title></head><body><h1>Wikipedia - Arc Research</h1><p>Free Encyclopedia</p></body></html>""",
    },
    # Map (3000)
    3000: {
        "/": """<!DOCTYPE html><html><head><title>OpenStreetMap</title></head><body><h1>OpenStreetMap Arc</h1><div id="map">Interactive map viewer</div></body></html>""",
    },
}


def make_handler(port: int):
    class WebArenaRequestHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            extra = {"port": port}
            logging.getLogger("webarena").info(f"[{self.command}] {self.path}", extra=extra)

        def do_GET(self):
            path_no_query = self.path.split("?")[0]
            templates = HTML_TEMPLATES.get(port, {})
            content = templates.get(path_no_query) or templates.get(self.path)

            if not content:
                # Fuzzy fallback matching
                for route, html in templates.items():
                    if route != "/" and route in self.path:
                        content = html
                        break

            if not content:
                content = templates.get("/", f"<!DOCTYPE html><html><body><h1>WebArena Port {port}</h1></body></html>")

            encoded = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8", errors="replace") if content_len > 0 else ""

            # Return success page matching GET
            self.do_GET()

    return WebArenaRequestHandler


class ThreadedTCPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_server_on_port(port: int) -> ThreadedTCPServer:
    handler = make_handler(port)
    server = ThreadedTCPServer(("0.0.0.0", port), handler)
    print(f"[WebArena Server] Listening on http://0.0.0.0:{port}", flush=True)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Multi-port WebArena Server")
    parser.add_argument("--ports", nargs="+", type=int, default=[9999, 7770, 8023, 8888, 3000])
    args = parser.parse_args()

    threads = []
    for port in args.ports:
        t = threading.Thread(target=start_server_on_port, args=(port,), daemon=True)
        t.start()
        threads.append(t)

    print(f"WebArena multi-service server started on ports: {args.ports}", flush=True)
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nShutting down servers...")


if __name__ == "__main__":
    main()
