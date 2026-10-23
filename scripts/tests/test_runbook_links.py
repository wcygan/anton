"""Source contract: every alert runbook_url resolves to an existing document and heading.

Alerts link responders to repository docs. A docs rewrite that drops or renames
a heading silently breaks those links; on 2026-10-23 an unmerged docs branch
removed all five site anchors that 23 alerts use.
"""

from pathlib import Path
import re
import unittest


REPO = Path(__file__).resolve().parents[2]
SITE = re.compile(r"https://wcygan\.github\.io/anton/(?P<route>[^#\s\"']+?)/?(?:#(?P<anchor>[^\s\"']+))?$")
BLOB = re.compile(r"https://github\.com/wcygan/anton/blob/main/(?P<path>[^#\s\"']+)(?:#(?P<anchor>[^\s\"']+))?$")
RUNBOOK = re.compile(r"runbook_url:\s*[\"']?(?P<url>[^\s\"']+)")
# github-slugger, which Docusaurus and GitHub both use for heading ids.
PUNCTUATION = re.compile(r"[ -⁯⸀-⹿\\'!\"#$%&()*+,./:;<=>?@\[\]^`{|}~]")
EXPLICIT_ID = re.compile(r"\s*\{#(?P<id>[^}]+)\}\s*$")
MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def slug(heading):
    return PUNCTUATION.sub("", MARKDOWN_LINK.sub(r"\1", heading).strip().lower()).replace(" ", "-")


def heading_ids(document):
    ids, seen, fenced = set(), {}, False
    for line in document.read_text().splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        match = None if fenced else re.match(r"#{1,6}\s+(.*)", line)
        if not match:
            continue
        explicit = EXPLICIT_ID.search(match.group(1))
        base = explicit.group("id") if explicit else slug(match.group(1))
        count = seen.get(base, 0)
        seen[base] = count + 1
        ids.add(base if count == 0 else f"{base}-{count}")
    return ids


def site_document(route):
    base = REPO / "docs/docs" / route
    for candidate in (base.with_suffix(".md"), base.with_suffix(".mdx"), base / "index.md", base / "README.md"):
        if candidate.is_file():
            return candidate
    return None


def problem(url):
    """Return why a repository runbook link is broken, or None when it resolves or is external."""
    if site := SITE.match(url):
        document, anchor = site_document(site.group("route")), site.group("anchor")
    elif blob := BLOB.match(url):
        document, anchor = REPO / blob.group("path"), blob.group("anchor")
        document = document if document.is_file() else None
    else:
        return None
    if document is None:
        return "no such document"
    if anchor and document.suffix in (".md", ".mdx") and anchor not in heading_ids(document):
        return f"no heading with id {anchor!r} in {document.relative_to(REPO)}"
    return None


def runbook_urls():
    for manifest in sorted((REPO / "kubernetes").rglob("*.yaml")):
        for match in RUNBOOK.finditer(manifest.read_text()):
            yield manifest.relative_to(REPO), match.group("url")


class RunbookLinkTests(unittest.TestCase):
    def test_every_runbook_url_resolves_to_a_document_and_heading(self):
        urls = list(runbook_urls())
        self.assertGreater(len(urls), 10, "runbook_url scan found almost nothing; check the pattern")
        broken = [f"{path}: {url}: {reason}" for path, url in urls if (reason := problem(url))]
        self.assertEqual(broken, [])

    def test_a_missing_heading_or_document_is_reported(self):
        self.assertIn("no heading", problem("https://wcygan.github.io/anton/guides/seaweedfs#no-such-heading"))
        self.assertEqual(problem("https://wcygan.github.io/anton/guides/no-such-page"), "no such document")
        self.assertEqual(problem("https://github.com/wcygan/anton/blob/main/docs/missing.md"), "no such document")
        self.assertIsNone(problem("https://github.com/cilium/cilium/issues/42007"))

    def test_slug_matches_docusaurus_heading_ids(self):
        self.assertEqual(slug("Integrity and read alerts"), "integrity-and-read-alerts")
        self.assertEqual(slug("Repair one read-only copy from its healthy peer"),
                         "repair-one-read-only-copy-from-its-healthy-peer")
        self.assertEqual(slug("`fs.configure` and [S3](https://x): notes"), "fsconfigure-and-s3-notes")


if __name__ == "__main__":
    unittest.main()
