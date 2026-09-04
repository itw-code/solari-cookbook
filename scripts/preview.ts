import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = parseInt(process.env.PORT || "8080", 10);
const DOCS_DIR = path.resolve(__dirname, "../docs");

const MIME_TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".mp4": "video/mp4",
  ".ico": "image/x-icon",
  ".txt": "text/plain; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
};

const server = http.createServer((req, res) => {
  let reqPath = decodeURIComponent(req.url?.split("?")[0] || "/");
  if (reqPath === "/" || reqPath === "") {
    reqPath = "/index.html";
  }

  let filePath = path.join(DOCS_DIR, reqPath);

  if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
    filePath = path.join(filePath, "index.html");
  }

  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    res.writeHead(404, { "Content-Type": "text/plain" });
    res.end("404 Not Found: " + reqPath);
    return;
  }

  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME_TYPES[ext] || "application/octet-stream";

  res.writeHead(200, { "Content-Type": contentType });
  fs.createReadStream(filePath).pipe(res);
});

function startServer(port: number) {
  server.removeAllListeners("error");
  server.once("error", (err: any) => {
    if (err.code === "EADDRINUSE") {
      console.log(`Port ${port} is in use, trying ${port + 1}...`);
      startServer(port + 1);
    } else {
      console.error("Server error:", err);
    }
  });

  server.listen(port, () => {
    console.log(`\n==============================================================`);
    console.log(`🚀 GitHub Pages Local Preview Server Running!`);
    console.log(`   👉 http://localhost:${port}/`);
    console.log(`   Serving: ${DOCS_DIR}`);
    console.log(`==============================================================\n`);
  });
}

startServer(PORT);

