#!/usr/bin/env python3
"""Publish rendered episodes as a podcast feed.

`render.py` stops at an mp3 sitting in `episodes/`, which means the only way to
hear an episode is to open that folder on the machine that made it. This turns
the folder into a feed a phone can subscribe to.

    python station.py build            # episodes/*.json + *.mp3 -> feed.xml
    python station.py serve            # serve the folder on the tailnet

What goes into each item: title from the script, duration measured by ffprobe,
enclosure length from the file itself, `pubDate` from the mp3 mtime, and the
show notes from `notes/<slug>.md` — the URLs under its `# Sources` heading, or,
when that file has no such heading, the URLs in its opening lines. A missing or
unprobeable mp3 is skipped with a warning and a non-zero exit, never a broken
item in the feed.

The guid is the slug, not the URL: a tailnet address changes, a guid must not,
or every podcatcher re-downloads the whole archive.
"""
import argparse
import datetime
import email.utils
import functools
import http.server
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NS)

DEFAULT_PORT = 8765
DEFAULT_TITLE = "Notebook Podcast"
DEFAULT_LANGUAGE = "en-us"
DEFAULT_DESCRIPTION = "Audio explainers rendered from notebook scripts."
SUMMARY_CHARS = 240
TOP_LINES = 25        # notes without a Sources heading: URLs come from the top


def warn(msg):
    print(f"station: {msg}", file=sys.stderr)


def hhmmss(seconds):
    """Seconds -> `10:43` / `1:02:05`, the `itunes:duration` shorthand."""
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def probe_duration(path):
    """Duration in seconds from ffprobe; raise with ffprobe's own words."""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=nw=1:nk=1", path]
    try:
        res = subprocess.run(cmd, check=True, capture_output=True, text=True,
                             timeout=60)
    except FileNotFoundError:
        raise RuntimeError("ffprobe not found — install ffmpeg")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffprobe timed out on {os.path.basename(path)}")
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "").strip().splitlines()
        raise RuntimeError("ffprobe failed on "
                           f"{os.path.basename(path)}"
                           + (f": {detail[-1]}" if detail else ""))
    out = res.stdout.strip()
    try:
        return float(out)
    except ValueError:
        raise RuntimeError(f"ffprobe reported no duration for "
                           f"{os.path.basename(path)}: {out!r}")


def tailnet_host():
    """This machine's first tailscale IPv4 address, or None if unavailable."""
    try:
        res = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                             text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    for line in res.stdout.splitlines():
        if line.strip():
            return line.strip()
    return None


def default_base_url(port):
    """Absolute URLs are required by every client; loopback silently breaks phones."""
    host = tailnet_host()
    if host is None:
        warn("tailscale gave no address; using 127.0.0.1 — a phone cannot reach "
             "that, pass --base-url (or subscribe from this machine only)")
        host = "127.0.0.1"
    return f"http://{host}:{port}"


HEADING = re.compile(r"^#{1,6}\s+(.*)$")
URL = re.compile(r"https?://[^\s)\]>\"',]+")


def notes_sources(path):
    """URLs from a notes file: the Sources section, else the opening lines."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return []

    in_sources = False
    found = []
    for line in lines:
        m = HEADING.match(line.strip())
        if m:
            in_sources = "source" in m.group(1).lower()
            continue
        if in_sources:
            found.extend(URL.findall(line))
    if not found:
        for line in lines[:TOP_LINES]:
            found.extend(URL.findall(line))

    seen = []
    for url in found:
        if url not in seen:
            seen.append(url)
    return seen


def fallback_summary(spec):
    """First sentence of the script — the show note when there is no notes file."""
    units = spec.get("paragraphs") or spec.get("lines") or []
    for unit in units:
        text = (unit.get("text") or "").strip()
        if not text:
            continue
        m = re.match(r"(.+?[.!?])(?:\s|$)", text)
        sentence = (m.group(1) if m else text).strip()
        if len(sentence) > SUMMARY_CHARS:
            sentence = sentence[:SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"
        return sentence
    return spec.get("title", "") or ""


def discover(episodes_dir):
    """(slug, script path, expected mp3 path) for every script, name-sorted."""
    out = []
    for name in sorted(os.listdir(episodes_dir)):
        if not name.endswith(".json"):
            continue
        slug = name[:-len(".json")]
        out.append((slug,
                    os.path.join(episodes_dir, name),
                    os.path.join(episodes_dir, slug + ".mp3")))
    return out


def collect(episodes_dir, notes_dir, base_url):
    """Read every episode into an item dict; return (items, skipped slugs)."""
    items, skipped = [], []
    for slug, script_path, mp3 in discover(episodes_dir):
        if not os.path.exists(mp3):
            warn(f"skipping {slug}: no {os.path.basename(mp3)} beside the script")
            skipped.append(slug)
            continue
        try:
            with open(script_path, encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError) as e:
            warn(f"skipping {slug}: unreadable script ({e})")
            skipped.append(slug)
            continue
        try:
            duration = probe_duration(mp3)
        except RuntimeError as e:
            warn(f"skipping {slug}: {e}")
            skipped.append(slug)
            continue
        if duration <= 0:
            warn(f"skipping {slug}: measured duration is zero")
            skipped.append(slug)
            continue
        if not isinstance(spec, dict):
            warn(f"skipping {slug}: script is not a JSON object")
            skipped.append(slug)
            continue

        notes = os.path.join(notes_dir, slug + ".md")
        sources = notes_sources(notes)
        description = "\n".join(sources) if sources else fallback_summary(spec)
        mtime = os.path.getmtime(mp3)
        items.append({
            "slug": slug,
            "title": str(spec.get("title") or slug),
            "description": description,
            "duration": duration,
            "length": os.path.getsize(mp3),
            "mtime": mtime,
            "url": f"{base_url}/episodes/{slug}.mp3",
        })
    items.sort(key=lambda i: i["mtime"], reverse=True)
    return items, skipped


def render(items, base_url, channel_title, language, description):
    """Assemble the RSS document bytes from collected items."""
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = channel_title
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = language
    ET.SubElement(channel, "generator").text = "station"
    ET.SubElement(channel, "lastBuildDate").text = email.utils.format_datetime(
        datetime.datetime.now(datetime.timezone.utc))
    ET.SubElement(channel, f"{{{ITUNES_NS}}}author").text = channel_title

    for it in items:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = it["title"]
        ET.SubElement(item, "description").text = it["description"]
        guid = ET.SubElement(item, "guid", {"isPermaLink": "false"})
        guid.text = it["slug"]
        ET.SubElement(item, "pubDate").text = email.utils.format_datetime(
            datetime.datetime.fromtimestamp(it["mtime"], datetime.timezone.utc))
        ET.SubElement(item, "enclosure", {
            "url": it["url"],
            "length": str(it["length"]),
            "type": "audio/mpeg",
        })
        ET.SubElement(item, f"{{{ITUNES_NS}}}duration").text = hhmmss(it["duration"])

    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True) + b"\n"


def build(episodes_dir="episodes", notes_dir="notes", out="feed.xml",
          base_url=None, port=DEFAULT_PORT, channel_title=DEFAULT_TITLE,
          language=DEFAULT_LANGUAGE, limit=None, description=DEFAULT_DESCRIPTION):
    """Write `out` and return (xml bytes, included slugs, skipped slugs)."""
    if not os.path.isdir(episodes_dir):
        raise SystemExit(f"station: no episodes directory: {episodes_dir}")
    base_url = (base_url or default_base_url(port)).rstrip("/")
    items, skipped = collect(episodes_dir, notes_dir, base_url)
    if limit is not None:
        items = items[:max(limit, 0)]
    xml_bytes = render(items, base_url, channel_title, language, description)
    with open(out, "wb") as f:
        f.write(xml_bytes)
    return xml_bytes, [i["slug"] for i in items], skipped


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Directory listing is pointless here; keep the log to one short line."""

    def log_message(self, format, *args):
        sys.stderr.write("station: " + (format % args) + "\n")


def serve(root=".", host=None, port=DEFAULT_PORT):
    """Serve `root` over HTTP so a podcatcher can fetch the feed and the mp3s."""
    root = os.path.abspath(root)
    host = host or (tailnet_host() or "127.0.0.1")
    feed = os.path.join(root, "feed.xml")
    if not os.path.exists(feed):
        warn(f"no feed.xml in {root} — run `station.py build` first")
    handler = functools.partial(QuietHandler, directory=root)
    try:
        httpd = http.server.ThreadingHTTPServer((host, port), handler)
    except OSError as e:
        raise SystemExit(f"station: cannot listen on {host}:{port} ({e})")

    print(f"feed: http://{host}:{port}/feed.xml", flush=True)
    if host in ("127.0.0.1", "localhost", "::1"):
        print("note: bound to loopback — reachable from this machine only",
              flush=True)
    else:
        print(f"note: if a host firewall is on, allow the port on the tailnet "
              f"interface only: sudo ufw allow in on tailscale0 to any port "
              f"{port} proto tcp", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("", flush=True)
    finally:
        httpd.server_close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="write feed.xml from episodes/")
    b.add_argument("-d", "--episodes", default="episodes")
    b.add_argument("--notes", default="notes", help="dir holding <slug>.md (default: notes)")
    b.add_argument("-o", "--out", default="feed.xml")
    b.add_argument("--base-url", default=None,
                   help="absolute prefix for enclosure URLs (default: this "
                        "machine's tailnet address)")
    b.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help="port used to build the default base URL")
    b.add_argument("--title", default=DEFAULT_TITLE, help="channel title")
    b.add_argument("--description", default=DEFAULT_DESCRIPTION)
    b.add_argument("--language", default=DEFAULT_LANGUAGE)
    b.add_argument("--limit", type=int, default=None, help="newest N episodes only")

    s = sub.add_parser("serve", help="serve the project dir so a podcatcher can fetch it")
    s.add_argument("-d", "--dir", default=".")
    s.add_argument("--host", default=None, help="default: this machine's tailnet address")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)

    args = ap.parse_args(argv)
    if args.cmd == "build":
        xml_bytes, items, skipped = build(
            episodes_dir=args.episodes, notes_dir=args.notes, out=args.out,
            base_url=args.base_url, port=args.port, channel_title=args.title,
            language=args.language, limit=args.limit, description=args.description)
        total = sum(1 for _ in ET.fromstring(xml_bytes).iter("item"))
        print(f"wrote {args.out}: {total} episode{'s' if total != 1 else ''}"
              + (f", skipped {', '.join(skipped)}" if skipped else ""))
        return 1 if skipped else 0
    serve(root=args.dir, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
