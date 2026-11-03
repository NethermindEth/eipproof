import os
import sys
from html.parser import HTMLParser
from urllib.parse import urlsplit

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
RAW = {"script", "style"}


class Checker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors, self.links, self.ids = [], [], [], set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            if a["id"] in self.ids and tag != "template":
                self.errors.append(f"duplicate id {a['id']!r}")
            self.ids.add(a["id"])
        for key in ("href", "src"):
            if a.get(key):
                self.links.append(a[key])
        if tag not in VOID:
            self.stack.append((tag, self.getpos()))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1][0] != tag:
            want = self.stack[-1][0] if self.stack else None
            self.errors.append(f"line {self.getpos()[0]}: </{tag}> closes <{want}>")
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    break
            return
        self.stack.pop()


def check_page(text):
    p = Checker()
    p.feed(text)
    p.close()
    errs = list(p.errors)
    if not text.lstrip().lower().startswith("<!doctype html>"):
        errs.append("no doctype")
    errs += [f"unclosed <{t}> from line {pos[0]}" for t, pos in p.stack]
    return errs, p.links


def check_dir(root):
    errs = []
    for dirpath, _, files in os.walk(root):
        for name in sorted(files):
            if not name.endswith(".html"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            page_errs, links = check_page(open(path).read())
            errs += [f"{rel}: {e}" for e in page_errs]
            for href in links:
                u = urlsplit(href)
                if u.scheme or u.netloc or href.startswith(("#", "mailto:", "javascript:")) or not u.path:
                    continue
                target = os.path.normpath(os.path.join(dirpath, u.path))
                if not os.path.exists(target):
                    errs.append(f"{rel}: broken link {href}")
    return errs


def main(argv=None):
    root = (sys.argv[1:] if argv is None else argv or ["site"])[0]
    errs = check_dir(root)
    for e in errs:
        print(f"::error title=sitecheck::{e}")
    print(f"sitecheck {root}: {len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
