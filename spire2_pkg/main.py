import argparse
import gzip
import json
import os
import re
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

# Optional Playwright import for Cloudflare bypass
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

PAGE_URL = "https://mobalytics.gg/slay-the-spire-2/tier-lists/cards"
CACHE_DIR = Path.home() / ".spire2"
MAPPING_FILENAME = "mappings.txt"
METADATA_FILENAME = "metadata.json"

# Default headers that mimic a real browser (prevents 403 blocking)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}


# ---------------------------------------------------------------------------
# scraping/helpers
# ---------------------------------------------------------------------------

def scrape_with_playwright(url: str) -> Optional[str]:
    """Use Playwright to render JavaScript and bypass Cloudflare challenge.
    
    Args:
        url: The URL to scrape
        
    Returns:
        HTML content as string if successful, None otherwise
    """
    if not PLAYWRIGHT_AVAILABLE:
        return None
    
    try:
        with sync_playwright() as p:
            # Use chromium with headless mode
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            
            try:
                # Navigate and wait for network to be idle
                page.goto(url, wait_until="networkidle", timeout=30000)
                
                # Get the rendered HTML
                html = page.content()
                browser.close()
                return html
            except Exception as e:
                print(f"Playwright navigation error: {e}")
                try:
                    browser.close()
                except:
                    pass
                return None
    except Exception as e:
        print(f"Playwright error: {e}")
        return None

def make_request_with_retry(url: str, max_retries: int = 3, timeout: int = 10, use_curl: bool = False) -> Optional[requests.Response]:
    """Make an HTTP GET request with exponential backoff and retries.
    
    Args:
        url: The URL to request
        max_retries: Maximum number of retries (default 3)
        timeout: Request timeout in seconds (default 10)
        use_curl: If True, use curl instead of requests library
        
    Returns:
        Response object if successful, None if all retries failed
    """
    if use_curl:
        # Try using curl as a fallback - it handles Cloudflare better
        for attempt in range(max_retries):
            try:
                cmd = [
                    "curl",
                    "-L",
                    "-s",
                    "--max-time", str(timeout),
                    "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "-H", "Accept-Language: en-US,en;q=0.5",
                    "-H", "Accept-Encoding: gzip, deflate",
                    "-H", "DNT: 1",
                    "-H", "Connection: keep-alive",
                    "-H", "Upgrade-Insecure-Requests: 1",
                    url
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
                if result.returncode == 0 and result.stdout:
                    # Create a mock response object with proper encoding handling
                    # Handle gzip compression
                    content = result.stdout
                    try:
                        # Try to decompress if gzipped
                        if content[:2] == b'\x1f\x8b':  # gzip magic number
                            content = gzip.decompress(content)
                    except Exception:
                        pass  # Not gzipped or decompression failed, use as-is
                    
                    class MockResponse:
                        def __init__(self, content):
                            # Handle encoding issues - replace with UTF-8 replacement char
                            if isinstance(content, bytes):
                                self.content = content
                            else:
                                self.content = content.encode('utf-8', errors='replace')
                            self.status_code = 200
                            self.text = self.content.decode('utf-8', errors='replace')
                    return MockResponse(content)
                else:
                    wait_time = (2 ** attempt)
                    if attempt < max_retries - 1:
                        print(f"curl request failed on attempt {attempt + 1}/{max_retries}, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        print(f"curl request failed after {max_retries} attempts")
                        return None
            except Exception as e:
                print(f"curl error: {e}")
                return None
    
    # Regular requests-based retry logic
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout:
            wait_time = (2 ** attempt)  # exponential backoff: 1, 2, 4 seconds
            if attempt < max_retries - 1:
                print(f"Timeout on attempt {attempt + 1}/{max_retries}, retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"Request timed out after {max_retries} attempts")
                return None
        except requests.exceptions.ConnectionError:
            wait_time = (2 ** attempt)
            if attempt < max_retries - 1:
                print(f"Connection error on attempt {attempt + 1}/{max_retries}, retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"Connection failed after {max_retries} attempts")
                return None
        except requests.exceptions.HTTPError as e:
            # Retry on 5xx server errors, 429 rate limit, and 403 Forbidden (may be transient or Cloudflare)
            if 500 <= e.response.status_code < 600 or e.response.status_code in (403, 429):
                wait_time = (2 ** attempt)
                if attempt < max_retries - 1:
                    print(f"HTTP error {e.response.status_code} on attempt {attempt + 1}/{max_retries}, will try curl if available...")
                    # If we get 403, try curl as a fallback
                    if e.response.status_code == 403 and attempt == max_retries - 2:
                        print("Trying curl fallback...")
                        curl_resp = make_request_with_retry(url, max_retries=1, timeout=timeout, use_curl=True)
                        if curl_resp:
                            return curl_resp
                    time.sleep(wait_time)
                else:
                    print(f"HTTP error {e.response.status_code} after {max_retries} attempts")
                    return None
            else:
                # Don't retry on other 4xx errors
                print(f"HTTP error {e.response.status_code}: {e}")
                return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None
    
    return None

def scrape_images(url: str, save_root: Optional[str] = None) -> List[Dict]:
    """Scrape image URLs for every tier list on the page.

    The algorithm mirrors the original standalone script.
    It returns a list of dictionaries with ``champion``, ``tier`` and ``url``
    keys.  If ``save_root`` is provided the images are also downloaded and
    written under the requested directory.
    
    Uses requests first, falls back to curl, then Playwright if Cloudflare
    challenge is detected.
    """

    resp = make_request_with_retry(url)
    html_content = None
    
    # If requests failed, try curl as a more robust fallback
    if not resp:
        print("Requests failed, attempting curl fallback...")
        resp = make_request_with_retry(url, use_curl=True)
    
    # Check if we got Cloudflare challenge page (indicated by "Just a moment" title)
    if resp:
        try:
            if "just a moment" in resp.content.decode('utf-8', errors='ignore').lower():
                print("Detected Cloudflare challenge, switching to browser rendering...")
                resp = None
        except:
            pass
    
    # If requests/curl failed or returned challenge page, try Playwright
    if not resp:
        if PLAYWRIGHT_AVAILABLE:
            print("Using Playwright to bypass Cloudflare challenge...")
            html_content = scrape_with_playwright(url)
            if not html_content:
                print("Playwright also failed")
                return []
        else:
            print(f"Failed to fetch {url}")
            return []
    else:
        html_content = resp.content

    try:
        soup = BeautifulSoup(html_content, "html.parser")
    except Exception as e:
        print(f"Failed to parse HTML: {e}")
        return []
    
    results: List[Dict] = []

    def safe_dir(name: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]", "_", name.strip().lower())

    try:
        for hdr in soup.find_all("header"):
            hdr_text = hdr.get_text(separator=" ").strip()
            if "tier list" not in hdr_text.lower():
                continue
            # Clean up champion name by removing "Tier List Save as Image" suffix
            champion = hdr_text.replace("Tier List Save as Image", "").strip()
            if not champion:
                champion = hdr_text  # Fallback to original if cleaning removes everything
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
                        # Use retry logic for image downloads too
                        img_resp = make_request_with_retry(src, timeout=10)
                        if img_resp:
                            try:
                                with open(os.path.join(tier_dir, fname), "wb") as f:
                                    f.write(img_resp.content)
                            except Exception as e:
                                print(f"failed to write {fname}: {e}")
                        else:
                            print(f"failed to download {src}")
    except Exception as e:
        print(f"Error while parsing page structure: {e}")
        # Return what we've collected so far - partial results are better than none
        if results:
            print(f"Warning: Parsing completed with {len(results)} cards, but encountered an error")
        return results

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
    
    # Preserve old cache before attempting refresh
    old_cache = None
    if mapfile.exists() and mapfile.stat().st_size > 0:
        old_cache = mapfile.read_text(encoding="utf-8")
    
    cards = scrape_images(PAGE_URL, save_root=save_root)
    
    # If scraping failed, keep the old cache and return existing mappings
    if not cards:
        if old_cache:
            print("Scraping failed, restoring cached card data...")
            mapfile.write_text(old_cache, encoding="utf-8")
            return load_mappings(str(mapfile))
        else:
            print("\nError: Could not fetch card data and no valid cache exists")
            if not PLAYWRIGHT_AVAILABLE:
                print("\nTo fetch card data, you need to install Playwright:")
                print("  pip install playwright")
                print("\nOr use the system Python (which has Playwright installed):")
                print("  /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 -m spire2_pkg.main --tier")
            return []
    
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
    parser.add_argument(
        "--tier",
        action="store_true",
        help="enter interactive tier lookup REPL (case-insensitive)",
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
    if args.tier:
        # interactive REPL loop; the cache and cards have already been loaded above
        interactive_tier_loop(cards)
    elif args.search:
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


def interactive_tier_loop(cards: List[Dict]) -> None:
    """Run a simple REPL that looks up card tiers by name.

    The loop continues until the user types ``exit`` or ``quit`` or hits
    Ctrl+C/EOF. Input is treated case-insensitively and spaces may be used
    without quoting. A minimal prompt (``>> ``) is displayed to match the
    user's specification.
    """
    try:
        while True:
            user = input(">> ").strip()
            if not user:
                continue
            if user.lower() in ("exit", "quit"):
                break
            found = False
            lookup = user.lower()
            for entry in cards:
                if entry.get("name", "").lower() == lookup:
                    tier = entry.get("tier", "?")
                    print(f"This card is tier {tier}.")
                    found = True
                    break
            if not found:
                print("Card not found.")
    except (KeyboardInterrupt, EOFError):
        # graceful exit on Ctrl+C or EOF
        print()


if __name__ == "__main__":
    main()