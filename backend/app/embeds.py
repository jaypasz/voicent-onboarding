"""Links and embeds from other tools: a Loom or YouTube video, a Figma file, a Google Doc or Drive folder, a Notion page.

A template gives a plain https address. `describe` says what it is and, for providers we know can be shown inside a page,
builds the embed address itself from the ids it parsed out. The address a template gave never goes into an iframe as it
is: only one of the embed addresses built here does, so a template can't frame an arbitrary site in the client's portal.
Anything else https is still offered as a link. Notion pages are a link only: Notion refuses to be framed unless a page
was published with embedding on, and a blank box is worse than a link.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, quote, urlsplit

ID = r"[A-Za-z0-9_-]"
GOOGLE_DOCS = {"document": ("google_doc", "Google Doc"), "spreadsheets": ("google_sheet", "Google Sheet"), "presentation": ("google_slides", "Google Slides")}
FIGMA_KINDS = ("file", "design", "proto", "board", "slides")
# The hosts an embed address built here can point at. The frontend checks the same list before it draws an iframe.
EMBED_HOSTS = ("www.loom.com", "www.youtube-nocookie.com", "player.vimeo.com", "www.figma.com", "docs.google.com", "drive.google.com")


def _https(url: str):
    if not isinstance(url, str) or len(url) > 500 or any(c.isspace() for c in url):
        return None
    try:
        u = urlsplit(url)
    except ValueError:
        return None
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.port not in (None, 443):
        return None
    return u


def describe(url: str) -> dict | None:
    """What a link is: {provider, kind, href, embed_url}. None if it isn't a usable https address."""
    u = _https(url)
    if u is None:
        return None
    host, path = u.hostname.lower(), u.path

    def out(provider: str, kind: str, embed: str | None = None) -> dict:
        return {"provider": provider, "kind": kind, "href": url, "embed_url": embed}

    if host in ("loom.com", "www.loom.com") and (mt := re.fullmatch(rf"/(?:share|embed)/({ID}{{10,64}})/?", path)):
        return out("loom", "Loom video", f"https://www.loom.com/embed/{mt.group(1)}")
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"):
        vid = None
        if host == "youtu.be":
            vid = path.strip("/")
        elif path == "/watch":
            vid = (parse_qs(u.query).get("v") or [""])[0]
        elif mt := re.fullmatch(r"/(?:embed|shorts|live)/([^/]+)/?", path):
            vid = mt.group(1)
        if vid and re.fullmatch(rf"{ID}{{11}}", vid):
            return out("youtube", "YouTube video", f"https://www.youtube-nocookie.com/embed/{vid}")
        return out("youtube", "YouTube")
    if host in ("vimeo.com", "www.vimeo.com", "player.vimeo.com"):
        if mt := re.fullmatch(r"(?:/video)?/(\d{3,12})(?:/([0-9a-f]{6,20}))?/?", path):
            h = mt.group(2) or (parse_qs(u.query).get("h") or [""])[0]
            suffix = f"?h={h}" if re.fullmatch(r"[0-9a-f]{6,20}", h or "") else ""
            return out("vimeo", "Vimeo video", f"https://player.vimeo.com/video/{mt.group(1)}{suffix}")
        return out("vimeo", "Vimeo")
    if host in ("figma.com", "www.figma.com"):
        if mt := re.fullmatch(rf"/({'|'.join(FIGMA_KINDS)})/([A-Za-z0-9]{{10,64}})(?:/[^/]*)?/?", path):
            canonical = f"https://www.figma.com/{mt.group(1)}/{mt.group(2)}"
            node = (parse_qs(u.query).get("node-id") or [""])[0]
            if re.fullmatch(r"[0-9]+[-:][0-9]+", node):
                canonical += f"?node-id={node}"
            return out("figma", "Figma file", f"https://www.figma.com/embed?embed_host=share&url={quote(canonical, safe='')}")
        return out("figma", "Figma")
    if host == "docs.google.com":
        if (mt := re.fullmatch(rf"/(document|spreadsheets|presentation)/d/({ID}{{10,128}})(?:/.*)?", path)):
            provider, kind = GOOGLE_DOCS[mt.group(1)]
            return out(provider, kind, f"https://docs.google.com/{mt.group(1)}/d/{mt.group(2)}/preview")
        return out("google_drive", "Google Docs")
    if host == "drive.google.com":
        if mt := re.fullmatch(rf"/file/d/({ID}{{10,128}})(?:/.*)?", path):
            return out("google_drive", "Google Drive file", f"https://drive.google.com/file/d/{mt.group(1)}/preview")
        if mt := re.fullmatch(rf"/drive/(?:u/\d+/)?folders/({ID}{{10,128}})/?", path):
            return out("google_drive", "Google Drive folder", f"https://drive.google.com/embeddedfolderview?id={mt.group(1)}#list")
        return out("google_drive", "Google Drive")
    if host in ("notion.so", "www.notion.so") or host.endswith(".notion.site"):
        return out("notion", "Notion page")
    return out("link", "Web link")


def resources(step_doc: dict) -> list[dict]:
    """A step's resources as the portal and the admin app show them: our label, plus what the link is."""
    out = []
    for r in step_doc.get("resources") or []:
        d = describe(r.get("url", ""))
        if d is not None:
            out.append({"label": r.get("label") or d["kind"], **d})
    return out


def media(step_doc: dict) -> dict | None:
    """The one thing a "Watch or read" step shows."""
    return describe((step_doc.get("config") or {}).get("url", "")) if step_doc.get("type") == "info_video" else None
