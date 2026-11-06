# The SDK site

The showcase page of the TigerTag Python SDK, published on GitHub Pages:
<https://tigertag-project.github.io/TigerTag-SDK-Python/>

It presents the SDK and sends readers to `pip install tigertag`, the
[PyPI page](https://pypi.org/project/tigertag/) and the README's quick start. It is static
HTML, one page per language, built by [`build.py`](build.py) and published by
[`pages.yml`](../.github/workflows/pages.yml) on every push to `main` that touches `site/`,
`README.md`, `CHANGELOG.md`, `pyproject.toml` or `llms.txt`. The same checks run on every
pull request (`test.yml`, job "site").

The `site/` folder is not part of the Python package: setuptools only packages `tigertag*`.

## Files

| File | Contents |
|---|---|
| [`template.html`](template.html) | The page. Every `{{key}}` is replaced by the text of that key in the page's language; `{{@…}}` keys are filled by `build.py` (language menu, `hreflang` links, JSON-LD, version, code samples). |
| [`i18n/en.json`](i18n/en.json) | The English text, which is the reference: every other language has exactly its keys. |
| `i18n/<lang>.json` | One file per language: `fr`, `de`, `es`, `it`, `zh` (Simplified Chinese), `pt` (Brazil), `pt-pt` (Portugal), `pl`, `ru`, `nl` — the languages of the other TigerTag sites. |
| [`site.css`](site.css), [`site.js`](site.js) | The look of the TigerTag protocol site (dark by default, light on request), the theme and language buttons, and the copy buttons. Each page loads them with `?v=` and a hash of the file's content. |
| [`assets/`](assets/) | The TigerTag head logos from the brand kit, unmodified: white on the dark theme, black (contouring) on the light one. The other pictures come from the repository's `assets/`. |

## Facts come from the repository

Nothing on the page is typed twice. `build.py` reads:

- the **code samples** from `README.md`, by section heading (`## Quick start`, `## Install`,
  `## Signature verification`, `## CLI`): the first code block of each section is shown as is;
- the **version** from `pyproject.toml` and its **release date** from `CHANGELOG.md`;
- the page's **dateModified** from the last git commit touching the site or those files.

The build stops if a section, a version or its dated CHANGELOG entry is missing. A new fact
on the page goes to the README first, then to `i18n/*.json`. Facts only: no ranking or
superlative without a dated source (`seo_check.py` refuses the common ones).

## Editing

- **Change a text**: edit `i18n/en.json`, then the same key in every other language.
- **Add a text**: add the key to every `i18n/*.json` file and use `{{key}}` in `template.html`.
  The build refuses a language that misses a key, has an unknown one or an empty value.
- **Check and preview**:

  ```bash
  python3 site/build.py --check
  python3 site/build.py && python3 -m http.server 8000 --directory _site
  python3 site/build.py --only en   # English only, while translations are pending
  ```

- **Search and answer engines**: `python3 site/build.py --out _site && python3 site/seo_check.py _site`
  checks every page (title and description length, one `h1`, canonical and `hreflang`,
  sharing cards, `alt` text, JSON-LD types and the FAQ they mirror, in-page links, the
  install command and the PyPI link, no unsupported superlative, sitemap, robots, `llms.txt`).

The English page is the root (`/`), every other language has its own folder (`/fr/`,
`/zh/`…). A language chosen in the menu is remembered, and the English root forwards to it on
the next visit.

## Before the first deploy

GitHub Pages must be set once to build from GitHub Actions: Settings > Pages > Source =
"GitHub Actions". Until then `pages.yml` fails at the deploy step.
