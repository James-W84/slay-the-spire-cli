import argparse
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

PAGE_URL = "https://mobalytics.gg/slay-the-spire-2/tier-lists/cards"
CACHE_DIR = Path.home() / ".spire2"
MAPPING_FILENAME = "mappings.txt"
METADATA_FILENAME = "metadata.json"


# ---------------------------------------------------------------------------
# scraping/helpers
# ---------------------------------------------------------------------------

def scrape_images(url: str, save_root: Optional[str] = None) -> List[Dict]:
    """Scrape image URLs for every tier list on the page.

    The algorithm mirrors the original standalone script.
    It returns a list of dictionaries with ``champion``, ``tier`` and ``url``
    keys.  If ``save_root`` is provided the images are also downloaded and
    written under the requested directory.
    """

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"Request failed: {e}")
        return []

    soup = BeautifulSoup(resp.content, "html.parser")
    results: List[Dict] = []

    def safe_dir(name: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]", "_", name.strip().lower())

    for hdr in soup.find_all("header"):
        hdr_text = hdr.get_text(separator=" ").strip()
        if "tier list" not in hdr_text.lower():
            continue
        champion = hdr_text
        section = hdr.find_parent("section")
        if not section:
            continue

        for label_div in section.find_all(
            "div", string=lambda t: t and t.strip() in ["S", "A", "B", "C", "D"]
        ):
            tier = label_div.get_text().strip()
            parent = label_div.parent
            card_container = parent.find_next_sibling("div")
            if not card_container:
                continue
            imgs = card_container.find_all("img")
            for img in imgs:
                src = img.get("src")
                if not src:
                    continue
                results.append({"champion": champion, "tier": tier, "url": src})

                # optionally save the actual file
                if save_root:
                    from urllib.parse import urlparse

                    champ_dir = os.path.join(save_root, safe_dir(champion))
                    tier_dir = os.path.join(champ_dir, tier.lower())
                    os.makedirs(tier_dir, exist_ok=True)

                    parsed = urlparse(src)
                    fname = os.path.basename(parsed.path)
                    try:
                        img_resp = requests.get(src, headers=headers, timeout=10)
                        img_resp.raise_for_status()
                        with open(os.path.join(tier_dir, fname), "wb") as f:
                            f.write(img_resp.content)
                    except Exception as e:
                        print(f"failed to download {src}: {e}")

    return results


# ---------------------------------------------------------------------------
# mapping utilities
# ---------------------------------------------------------------------------

def _name_from_url(u: str) -> str:
    from urllib.parse import urlparse
    import os

    fname = os.path.basename(urlparse(u).path)
    name = os.path.splitext(fname)[0]
    return name.replace("-", " ").title()



def extract_mappings(results: List[Dict], filepath: str) -> None:
    """Write a name->tier mapping file from scraper results."""
    with open(filepath, "w", encoding="utf-8") as f:
        for entry in results:
            url = entry.get("url")
            tier = entry.get("tier", "").upper()
            if not url or not tier:
                continue
            name = _name_from_url(url)
            f.write(f"'{name}'=>'{tier}'\n")



def load_mappings(filepath: str) -> List[Dict]:
    """Load a mapping file produced by :func:`extract_mappings`.

    The return value is a list of dicts containing ``name`` and ``tier``.
    Lines that do not conform to the expected pattern are silently skipped.
    """
    results: List[Dict] = []
    pattern = re.compile(r"'(?P<name>[^']+)'\s*=>\s*'?(?P<t>[SABCD])'?")
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            m = pattern.search(line)
            if not m:
                continue
            results.append({"name": m.group("name"), "tier": m.group("t")})
    return results


# ---------------------------------------------------------------------------
# caching logic
# ---------------------------------------------------------------------------

def ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def metadata_path() -> Path:
    return CACHE_DIR / METADATA_FILENAME


def mapping_path(custom: Optional[str] = None) -> Path:
    # allow override via CLI
    return Path(custom) if custom else CACHE_DIR / MAPPING_FILENAME


def load_metadata() -> Dict:
    mp = metadata_path()
    if not mp.exists():
        return {}
    try:
        return json.loads(mp.read_text())
    except Exception:
        return {}


def save_metadata(data: Dict) -> None:
    mp = metadata_path()
    mp.write_text(json.dumps(data))


def needs_refresh(mapfile: Path) -> bool:
    if not mapfile.exists():
        return True
    meta = load_metadata()
    ts = meta.get("last_fetched_timestamp")
    if not ts:
        return True
    try:
        last = datetime.fromisoformat(ts)
    except Exception:
        return True
    return datetime.now() - last > timedelta(days=3)


def refresh_data(mapfile: Path, save_root: Optional[str] = None) -> List[Dict]:
    msg = "First-time setup: Fetching card data..." if not mapfile.exists() else "Refreshing card data..."
    print(msg)
    cards = scrape_images(PAGE_URL, save_root=save_root)
    extract_mappings(cards, str(mapfile))
    save_metadata({"last_fetched_timestamp": datetime.now().isoformat()})
    return load_mappings(str(mapfile))


def load_cards(mapfile: Path, save_root: Optional[str] = None) -> List[Dict]:
    if needs_refresh(mapfile):
        return refresh_data(mapfile, save_root=save_root)
    return load_mappings(str(mapfile))


# ---------------------------------------------------------------------------
# command line entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query Slay the Spire 2 card tier lists."
    )
    parser.add_argument(
        "--search",
        metavar="TIER",
        help="show card names for the given tier letter (S/A/B/C/D)",
    )
    parser.add_argument(
        "--save",
        metavar="DIR",
        help="directory under which to download images organised by champion/tier",
    )
    parser.add_argument(
        "--map",
        metavar="FILE",
        help="path to mapping file (defaults to ~/.spire2/mappings.txt)",
        default=str(CACHE_DIR / MAPPING_FILENAME),
    )
    parser.add_argument(
        "--name",
        metavar="CARD",
        help="look up a card by name and display its tier",
    )
    args = parser.parse_args()

    cards: List[Dict] = []

    # determine whether we are using the internal cache file or a custom one
    default_map = str(CACHE_DIR / MAPPING_FILENAME)
    mapfile = mapping_path(None if args.map == default_map else args.map)

    # always ensure base cache directory exists (harmless even for custom paths)
    ensure_cache_dir()

    if args.map != default_map:
        # custom path: no automatic refresh behaviour
        if args.save or not mapfile.exists():
            page = PAGE_URL
            cards = scrape_images(page, save_root=args.save) if args.save else scrape_images(page)
            extract_mappings(cards, str(mapfile))
        else:
            cards = load_mappings(str(mapfile))
    else:
        # use cache-managed file
        cards = load_cards(mapfile, save_root=args.save)

    # processing commands
    if args.search:
        tier_letter = args.search.strip().upper()
        for entry in cards:
            if entry.get("tier", "").upper() == tier_letter:
                print(entry.get("name", entry.get("url", "")))
    elif args.name:
        target = args.name.strip().lower()
        found = False
        for entry in cards:
            cardname = entry.get("name", "").lower()
            if cardname == target:
                tier = entry.get("tier", "?")
                print(f"This card is tier {tier}")
                found = True
                break
        if not found:
            print(f"'{args.name}' not found")
    else:
        for entry in cards:
            line = entry.get("name", entry.get("url", ""))
            tier = entry.get("tier", "?")
            print(f"[{tier}] {line}")


if __name__ == "__main__":
    main()