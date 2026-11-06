# SPDX-License-Identifier: Apache-2.0
#
# TigerTag Python SDK
# Copyright (c) 2025-2026 TigerSystem.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Build the TigerTag Python SDK showcase site (GitHub Pages) into `_site/`.

One static page per language, all from `template.html` and `i18n/<lang>.json`:
English at the root, the others under `/<lang>/`. Every page is complete HTML in
its own language, with `hreflang` links between them, JSON-LD in its language and
a sitemap listing them all.

The code on the page is never typed twice: the samples are read from the
repository's README (by section heading), the version from `pyproject.toml` and
its release date from `CHANGELOG.md`, so the page always says what the README and
the package say. Standard library only, like the SDK's core.

Usage:
    python site/build.py                 # build into _site/
    python site/build.py --check         # only check the translations and sources
    python site/build.py --out DIR --url https://example.org/path/
"""

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SITE_URL = "https://tigertag-project.github.io/TigerTag-SDK-Python/"
REPO_URL = "https://github.com/TigerTag-Project/TigerTag-SDK-Python"
PYPI_URL = "https://pypi.org/project/tigertag/"

# The eleven languages of the TigerTag sites, in the same order. `pt` (Brazil)
# and `pt-pt` (Portugal) are separate dictionaries on purpose.
LANGS = ["en", "fr", "de", "es", "it", "zh", "pt", "pt-pt", "pl", "ru", "nl"]

# The share picture: tigersystem.io draws this page's card in each language,
# with the same renderer as its own pages, so the site keeps no picture of its own.
SHARE_CARD = "https://tigersystem.io/{lang}/sdk-python/opengraph-image"
HTML_LANG = {"zh": "zh-Hans", "pt": "pt-BR", "pt-pt": "pt-PT"}
OG_LOCALE = {"en": "en_US", "fr": "fr_FR", "de": "de_DE", "es": "es_ES", "it": "it_IT",
             "zh": "zh_CN", "pt": "pt_BR", "pt-pt": "pt_PT", "pl": "pl_PL", "ru": "ru_RU", "nl": "nl_NL"}

# Repository file -> published path under assets/.
ASSETS = {
    "assets/chip_layout.svg": "chip_layout.svg",
    "assets/favicon.svg": "favicon.svg",
    "assets/apple-touch-icon.png": "apple-touch-icon.png",
}

# README section heading -> (fence language, sample name). The first block of that
# language under the heading is shown on the page, exactly as the README has it.
SAMPLES = {
    "quickstart": ("## Quick start", "python"),
    "install": ("## Install", "bash"),
    "verify": ("## Signature verification", "python"),
    "cli": ("## CLI", "bash"),
}

# Crawlers of search and answer engines, welcomed by name in robots.txt (the same
# list as the protocol site). Listing them is an explicit opt-in, not a ranking trick.
AI_AGENTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User",
             "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended", "CCBot",
             "Amazonbot", "Bytespider", "Meta-ExternalAgent", "cohere-ai", "DuckAssistBot", "MistralAI-User"]

ORG_ID = "https://tigersystem.io/#organization"
PLACEHOLDER = re.compile(r"\{\{([a-z0-9_@]+)\}\}")


def asset_version(name):
    """Short sha256 of a published site file, appended to its URL as ?v=."""
    return hashlib.sha256((HERE / name).read_bytes()).hexdigest()[:10]


def package_version():
    """`version` of [project] in pyproject.toml (tomllib is 3.11+, the SDK supports 3.8)."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?ms)^\[project\]\s.*?^version\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("error: no version in pyproject.toml [project]")
    return match.group(1)


def release_date(version):
    """The date CHANGELOG.md gives to that version: `## [1.3.0] — 2026-09-30`."""
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"(?m)^## \[" + re.escape(version) + r"\][^\n]*?(\d{4}-\d{2}-\d{2})", text)
    if not match:
        raise SystemExit(f"error: CHANGELOG.md has no dated entry for {version}")
    return match.group(1)


def readme_samples():
    """The code blocks shown on the page, read from the README by section heading."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    samples = {}
    for name, (heading, fence) in SAMPLES.items():
        start = readme.find("\n" + heading + "\n")
        if start < 0:
            raise SystemExit(f"error: README.md has no section {heading!r} (sample {name!r})")
        match = re.compile(r"```" + fence + r"\n(.*?)\n```", re.S).search(readme, start)
        nxt = readme.find("\n## ", start + len(heading) + 1)
        if not match or (nxt >= 0 and match.start() > nxt):
            raise SystemExit(f"error: README.md section {heading!r} has no ```{fence} block")
        samples[name] = match.group(1)
    return samples


PY_KEYWORDS = r"\b(?:from|import|for|in|def|return|with|as|if|else|True|False|None|print)\b"
TOKENS = re.compile(r"(?P<com>#[^\n]*)|(?P<str>\"[^\"\n]*\"|'[^'\n]*')|(?P<kw>" + PY_KEYWORDS + r")|(?P<num>\b\d+\b)")


def highlight(code, lang):
    """Escaped HTML with a few spans for comments, strings, keywords and numbers."""
    out, pos = [], 0
    for m in TOKENS.finditer(code):
        kind = m.lastgroup
        if lang == "bash" and kind in ("kw", "num"):
            continue
        out.append(html.escape(code[pos:m.start()], quote=False))
        out.append(f'<span class="t-{kind}">{html.escape(m.group(0), quote=False)}</span>')
        pos = m.end()
    out.append(html.escape(code[pos:], quote=False))
    text = "".join(out)
    if lang == "bash":
        text = re.sub(r"(?m)^(?!<)(\S+)", r'<span class="t-cmd">\1</span>', text)
    return text


def site_date():
    """The page's last change as an ISO date, from git (site, README, CHANGELOG, pyproject)."""
    import subprocess
    from datetime import datetime, timezone
    try:
        day = subprocess.run(["git", "log", "-1", "--format=%cI", "--", "site", "README.md", "CHANGELOG.md", "pyproject.toml"],
                             cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()[:10]
    except (OSError, subprocess.CalledProcessError):
        day = ""
    return day or datetime.now(timezone.utc).date().isoformat()


def load_dictionaries():
    """Every language, checked against English: same keys, none empty."""
    dicts = {}
    for lang in LANGS:
        path = HERE / "i18n" / f"{lang}.json"
        if not path.exists():
            raise SystemExit(f"error: missing translation {path.relative_to(REPO)}")
        dicts[lang] = json.loads(path.read_text(encoding="utf-8"))
    reference = list(dicts["en"])
    problems = []
    for lang, words in dicts.items():
        missing = [k for k in reference if k not in words]
        extra = [k for k in words if k not in dicts["en"]]
        empty = [k for k, v in words.items() if not isinstance(v, str) or not v.strip()]
        for label, keys in (("missing", missing), ("unknown", extra), ("empty", empty)):
            if keys:
                problems.append(f"{lang}.json: {label} key(s): {', '.join(keys)}")
    template_keys = set(PLACEHOLDER.findall((HERE / "template.html").read_text(encoding="utf-8")))
    unused = [k for k in template_keys if not k.startswith("@") and k not in dicts["en"]]
    if unused:
        problems.append(f"template.html uses unknown key(s): {', '.join(sorted(unused))}")
    if problems:
        raise SystemExit("error: translations do not match en.json\n  " + "\n  ".join(problems))
    return dicts


def page_path(lang):
    return "" if lang == "en" else f"{lang}/"


def faq_count(template):
    return len(re.findall(r"\{\{faq(\d+)_q\}\}", template))


def render(template, lang, words, dicts, site_url, facts):
    base = "" if lang == "en" else "../"
    url = site_url + page_path(lang)
    hl = HTML_LANG.get(lang, lang)
    version, released, modified, samples = facts["version"], facts["released"], facts["modified"], facts["samples"]

    alternates = [f'<link rel="alternate" hreflang="{HTML_LANG.get(l, l)}" href="{site_url}{page_path(l)}">' for l in LANGS]
    alternates.append(f'<link rel="alternate" hreflang="x-default" href="{site_url}">')

    menu = []
    for l in LANGS:
        current = ' aria-current="true"' if l == lang else ""
        menu.append(f'          <li><a href="{base}{page_path(l)}" hreflang="{HTML_LANG.get(l, l)}" '
                    f'lang="{HTML_LANG.get(l, l)}" data-lang="{l}"{current}>{html.escape(dicts[l]["lang_name"])}</a></li>')

    faq = [{"@type": "Question", "name": words[f"faq{i}_q"],
            "acceptedAnswer": {"@type": "Answer", "text": words[f"faq{i}_a"]}}
           for i in range(1, faq_count(template) + 1)]
    jsonld = [
        {"@context": "https://schema.org", "@type": "Organization", "@id": ORG_ID, "name": "TigerSystem",
         "url": "https://tigersystem.io", "logo": site_url + "assets/apple-touch-icon.png",
         "sameAs": ["https://github.com/TigerTag-Project", "https://wiki.tigersystem.io",
                    "https://tigertag-project.github.io/TigerTag-RFID-Guide/"]},
        {"@context": "https://schema.org", "@type": "WebSite", "name": "TigerTag Python SDK", "url": url,
         "inLanguage": hl, "description": words["meta_description"], "publisher": {"@id": ORG_ID}},
        {"@context": "https://schema.org", "@type": "SoftwareSourceCode", "name": "TigerTag Python SDK",
         "description": words["meta_description"], "inLanguage": hl,
         "codeRepository": REPO_URL, "programmingLanguage": {"@type": "ComputerLanguage", "name": "Python"},
         "runtimePlatform": "Python 3.8+", "version": version, "dateModified": modified,
         "license": "https://www.apache.org/licenses/LICENSE-2.0",
         "isBasedOn": "https://github.com/TigerTag-Project/TigerTag-RFID-Guide",
         "author": {"@id": ORG_ID}, "publisher": {"@id": ORG_ID}},
        {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "tigertag",
         "alternateName": "TigerTag Python SDK", "description": words["meta_description"], "inLanguage": hl,
         "applicationCategory": "DeveloperApplication", "operatingSystem": "Windows, macOS, Linux",
         "softwareVersion": version, "datePublished": released, "downloadUrl": PYPI_URL,
         "installUrl": PYPI_URL, "softwareRequirements": "Python 3.8+", "url": url,
         "license": "https://www.apache.org/licenses/LICENSE-2.0", "author": {"@id": ORG_ID}},
        {"@context": "https://schema.org", "@type": "FAQPage", "inLanguage": hl, "mainEntity": faq},
    ]
    # `</` never appears inside a <script> block.
    jsonld_html = "\n".join('<script type="application/ld+json">' + json.dumps(j, ensure_ascii=False).replace("</", "<\\/") + "</script>"
                            for j in jsonld)

    special = {
        "@lang": lang,
        "@ogimage": SHARE_CARD.format(lang=lang),
        "@htmllang": hl,
        "@oglocale": OG_LOCALE[lang],
        "@oglocalealt": "\n".join(f'<meta property="og:locale:alternate" content="{OG_LOCALE[l]}">' for l in LANGS if l != lang),
        "@url": url,
        "@siteurl": site_url,
        "@base": base,
        "@langpath": page_path(lang),
        "@alternates": "\n".join(alternates),
        "@langmenu": "\n".join(menu),
        "@jsonld": jsonld_html,
        "@version": html.escape(version),
        "@released": released,
        "@pypi": PYPI_URL,
        "@repo": REPO_URL,
        # Content hashes: a new site.css / site.js gets a new URL, so no browser
        # keeps running the previous one from its cache.
        "@vcss": asset_version("site.css"),
        "@vjs": asset_version("site.js"),
        "@trademark": f'<a href="https://github.com/TigerTag-Project/TigerTag-RFID-Guide/blob/main/TRADEMARK.md">{html.escape(words["foot_trademark"])}</a>',
    }
    for name, (_, fence) in SAMPLES.items():
        special["@code_" + name] = highlight(samples[name], fence)

    def fill(match):
        key = match.group(1)
        if key in special:
            return special[key]
        return html.escape(words[key], quote=True)

    return PLACEHOLDER.sub(fill, template)


def gather():
    version = package_version()
    return {"version": version, "released": release_date(version), "modified": site_date(),
            "samples": readme_samples()}


def build(out, site_url):
    dicts = load_dictionaries()
    template = (HERE / "template.html").read_text(encoding="utf-8")
    facts = gather()
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)

    for lang in LANGS:
        target = out / page_path(lang) / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(template, lang, dicts[lang], dicts, site_url, facts), encoding="utf-8")

    for name in ("site.css", "site.js"):
        shutil.copy2(HERE / name, out / name)
    for source, published in ASSETS.items():
        shutil.copy2(REPO / source, out / "assets" / published)
    # Pictures made for the site itself (site/assets/): the TigerTag head logos,
    # white on the dark theme and black (contouring) on the light one.
    for extra in sorted((HERE / "assets").glob("*")):
        shutil.copy2(extra, out / "assets" / extra.name)
    # The SDK's machine-readable reference, at the site root too.
    shutil.copy2(REPO / "llms.txt", out / "llms.txt")

    urls = "\n".join(
        "  <url><loc>{}</loc><lastmod>{}</lastmod>{}</url>".format(
            site_url + page_path(lang), facts["modified"],
            "".join(f'<xhtml:link rel="alternate" hreflang="{HTML_LANG.get(l, l)}" href="{site_url}{page_path(l)}"/>' for l in LANGS))
        for lang in LANGS)
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
        f"{urls}\n</urlset>\n", encoding="utf-8")
    robots = ["User-agent: *", "Allow: /", ""]
    for agent in AI_AGENTS:
        robots += [f"User-agent: {agent}", "Allow: /", ""]
    robots += [f"Sitemap: {site_url}sitemap.xml"]
    (out / "robots.txt").write_text("\n".join(robots) + "\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"built {len(LANGS)} languages into {out} (tigertag {facts['version']}, released {facts['released']})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(REPO / "_site"))
    parser.add_argument("--url", default=SITE_URL)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--only", help="comma-separated languages, for a quick local preview")
    args = parser.parse_args()
    if args.only:
        LANGS[:] = [l for l in LANGS if l in args.only.split(",")]
    if args.check:
        load_dictionaries()
        gather()
        print(f"translations OK: {len(LANGS)} languages; README samples, version and release date found")
        return
    url = args.url if args.url.endswith("/") else args.url + "/"
    build(Path(args.out), url)


if __name__ == "__main__":
    sys.exit(main())
