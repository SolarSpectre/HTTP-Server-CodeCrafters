import asyncio
import argparse
import re
import sys
import gzip
from asyncio.streams import StreamReader, StreamWriter
from pathlib import Path

GLOBALS = {}

def stderr(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)

def parse_request(content: bytes) -> tuple[str, str, dict[str, str], str]:
    first_line, *tail = content.split(b"\r\n")
    method, path, _ = first_line.split(b" ")
    headers: dict[str, str] = {}
    while (line := tail.pop(0)) != b"":
        key, value = line.split(b": ")
        headers[key.decode()] = value.decode()
    return method.decode(), path.decode(), headers, b"".join(tail).decode()

def make_response(
    status: int,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> bytes:
    headers = headers or {}
    msg = {
        200: "OK",
        201: "Created",
        404: "Not Found",
    }
    response = f"HTTP/1.1 {status} {msg[status]}\r\n"
    response += "\r\n".join(f"{k}: {v}" for k, v in headers.items())
    response += f"\r\nContent-Length: {len(body)}\r\n\r\n"
    return response.encode() + body

def select_encoding(header: str) -> str:
    encodings = [e.strip() for e in header.split(",")]
    if "gzip" in encodings:
        return "gzip"
    return encodings[0] if encodings else ""

def gzip_compress(data: str) -> bytes:
    out = gzip.compress(data.encode())
    return out

async def handle_connection(reader: StreamReader, writer: StreamWriter) -> None:
    method, path, headers, body = parse_request(await reader.read(2**16))
    if re.fullmatch(r"/", path):
        writer.write(b"HTTP/1.1 200 OK\r\n\r\n")
        stderr(f"[OUT] /")
    elif re.fullmatch(r"/user-agent", path):
        ua = headers["User-Agent"]
        writer.write(make_response(200, {"Content-Type": "text/plain"}, ua.encode()))
        stderr(f"[OUT] user-agent {ua}")
    elif match := re.fullmatch(r"/echo/(.+)", path):
        msg = match.group(1)
        encoding_header = headers.get("Accept-Encoding", "")
        selected_encoding = select_encoding(encoding_header)
        if selected_encoding == "gzip":
            compressed_body = gzip_compress(msg)
            writer.write(make_response(200, {"Content-Encoding": "gzip", "Content-Type": "text/plain"}, compressed_body))
        else:
            writer.write(make_response(200, {"Content-Type": "text/plain"}, msg.encode()))
        stderr(f"[OUT] echo {msg}")
    elif match := re.fullmatch(r"/files/(.+)", path):
        p = Path(GLOBALS["DIR"]) / match.group(1)
        if method.upper() == "GET" and p.is_file():
            writer.write(
                make_response(
                    200,
                    {"Content-Type": "application/octet-stream"},
                    p.read_bytes(),
                )
            )
        elif method.upper() == "POST":
            p.write_bytes(body.encode())
            writer.write(make_response(201))
        else:
            writer.write(make_response(404))
        stderr(f"[OUT] file {path}")
    else:
        writer.write(make_response(404, {}, b""))
        stderr(f"[OUT] 404")
    await writer.drain()
    writer.close()
    await writer.wait_closed()

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default=".")
    args = parser.parse_args()
    GLOBALS["DIR"] = args.directory
    server = await asyncio.start_server(handle_connection, "localhost", 4221)
    async with server:
        stderr("Starting server...")
        stderr(f"--directory {GLOBALS['DIR']}")
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
