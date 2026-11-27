"""Fetch individual public social videos or direct video files into a job's staging directory."""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

from ..render.ffmpeg import Cancelled, CancelToken

MAX_BYTES = 512 * 1024 * 1024


class DownloadError(Exception):
    pass


def checked_url(url: str, expected: str | None = None) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise DownloadError("Enter a valid video URL.") from None
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or any(char.isspace() or ord(char) < 32 for char in url)):
        raise DownloadError("Enter an HTTP or HTTPS video URL.")
    host = parsed.hostname.removeprefix("www.")
    platform = "direct"
    if host in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}:
        platform = "youtube"
        video_id = r"[\w-]+"
        if host == "youtu.be":
            valid = re.fullmatch(rf"/{video_id}/?", parsed.path)
        elif parsed.path == "/watch":
            valid = re.fullmatch(video_id, parse_qs(parsed.query).get("v", [""])[0])
        else:
            valid = re.fullmatch(rf"/(shorts|live|embed)/{video_id}/?", parsed.path)
        if not valid:
            raise DownloadError("Enter a link to a single YouTube video or Short.")
    elif host == "instagram.com":
        platform = "instagram"
        if not re.fullmatch(r"/reels?/[\w-]+/?", parsed.path):
            raise DownloadError("Enter a link to an Instagram Reel.")
    if expected and expected != platform:
        raise DownloadError(f"Enter a {expected.title()} link in the matching field.")
    if platform != "direct" and port not in {None, 80, 443}:
        raise DownloadError("Use the standard platform video URL.")
    return platform


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, address: str):
        super().__init__(host, port, timeout=20, context=ssl.create_default_context())
        self.address = address

    def connect(self) -> None:
        sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except OSError:
            sock.close()
            raise


def _direct(url: str, folder: Path, cancel: CancelToken, progress: Callable[[float], None]) -> tuple[Path, str]:
    try:
        for _ in range(6):
            cancel.check("video download")
            checked_url(url)
            parsed = urlsplit(url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
            public = [address for address in addresses if ipaddress.ip_address(address).is_global]
            if not public or len(public) != len(addresses):
                raise DownloadError("Use a public video URL or add a local video file.")
            address = next((ip for ip in public if ":" not in ip), public[0])
            conn = (_PinnedHTTPS(host, port, address) if parsed.scheme == "https"
                    else http.client.HTTPConnection(address, port, timeout=20))
            try:
                target = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
                if parsed.query:
                    target += "?" + quote(parsed.query, safe="%&=+;/:?@!$'()*,-._~")
                conn.request("GET", target, headers={"Host": parsed.netloc, "Accept": "video/*, application/octet-stream"})
                with conn.getresponse() as response:
                    if response.status in {301, 302, 303, 307, 308} and response.getheader("Location"):
                        url = urljoin(url, response.getheader("Location"))
                        continue
                    if response.status != 200:
                        raise DownloadError(f"The video host returned HTTP {response.status}.")
                    total = response.length or 0
                    if total > MAX_BYTES:
                        raise DownloadError("The video exceeds the 512 MiB limit.")
                    chunk = response.read(12)
                    if chunk[4:8] == b"ftyp":
                        dest = folder / "video.mp4"
                    elif chunk.startswith(b"\x1a\x45\xdf\xa3"):
                        dest = folder / "video.webm"
                    else:
                        raise DownloadError("Use a direct MP4 or WebM link, or a public YouTube or Instagram video.")
                    received = len(chunk)
                    with dest.open("wb") as output:
                        output.write(chunk)
                        while chunk := response.read(256 * 1024):
                            cancel.check("video download")
                            received += len(chunk)
                            if received > MAX_BYTES:
                                raise DownloadError("The video exceeds the 512 MiB limit.")
                            output.write(chunk)
                            if total:
                                progress(min(1, received / total))
                    label = Path(unquote(parsed.path.rsplit("/", 1)[-1])).stem or "Downloaded video"
                    return dest, label[:120]
            finally:
                conn.close()
    except (OSError, http.client.HTTPException, ValueError):
        raise DownloadError("Couldn’t read the video from its host. Check that the link is public and try again.") from None
    raise DownloadError("The video link redirected too many times.")


class _QuietLogger:
    # Extractor diagnostics can contain signed URLs. Checkpoints use our own messages.
    def debug(self, _message: str) -> None: pass
    def warning(self, _message: str) -> None: pass
    def error(self, _message: str) -> None: pass


def fetch(url: str, folder: Path, cancel: CancelToken, progress: Callable[[float], None]) -> tuple[Path, str]:
    platform = checked_url(url)
    folder.mkdir(parents=True, exist_ok=True)
    if platform == "direct":
        return _direct(url, folder, cancel, progress)

    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError as ExtractorError

    def check_size(event: dict) -> None:
        cancel.check("video download")
        received = event.get("downloaded_bytes") or 0
        total = event.get("total_bytes") or event.get("total_bytes_estimate") or 0
        if max(received, total) > MAX_BYTES:
            raise DownloadError("The video exceeds the 512 MiB limit.")
        if total:
            progress(min(1, received / total))

    options = {
        "allowed_extractors": ["Youtube" if platform == "youtube" else "Instagram"],
        "noplaylist": True,
        "outtmpl": str(folder / "video.%(ext)s"),
        "format": "bv[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "max_filesize": MAX_BYTES,
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        "cachedir": False,
        "logger": _QuietLogger(),
        "progress_hooks": [check_size],
        "js_runtimes": {"node": {}},
    }
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url)
    except ExtractorError:
        cancel.check("video download")
        raise DownloadError(f"Couldn’t download this {platform.title()} video. Check that it is public and available.") from None
    except Cancelled:
        raise
    cancel.check("video download")
    results = [file for file in folder.glob("video.*") if file.suffix in {".mp4", ".webm", ".mkv", ".mov"}]
    if len(results) != 1 or results[0].stat().st_size > MAX_BYTES:
        raise DownloadError("The video could not be saved as a single file within the 512 MiB limit.")
    return results[0], str((info or {}).get("title") or platform.title())[:120]
