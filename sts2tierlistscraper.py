import requests
import re
from bs4 import BeautifulSoup


def scrape_images(url: str, save_root: str | None = None) -> list[dict]:
    """Scrape image URLs for every tier list on the page.

    Rather than being hard‑coded to the Regent list, the parser now examines
    every <header> whose text contains "tier list".  For each section it
    extracts the champion name ("Ironclad Tier List", "Silent Tier List",
    etc.) and then iterates the tiers beneath, recording every image
    discovered.

    The returned value is a list of dictionaries with the keys
    ``champion`` (string), ``tier`` (one of ``"S"``..``"D"``), and
    ``url`` (image location).

    If ``save_root`` is supplied the images are also fetched and written to
    disk beneath that directory.  The structure is

        <save_root>/<champion>/<tier_letter>/<filename>

    which matches the requested organisation (champion label first,
    followed by tier letter).
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"Request failed: {e}")
        return []

    soup = BeautifulSoup(resp.content, "html.parser")
    results: list[dict] = []

    def safe_dir(name: str) -> str:
        # turn header text into filesystem-safe directory name
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
                    import os
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



def _name_from_url(u: str) -> str:
    """Convert an image URL to a human readable card name.

    Example:

        https://.../largesse.webp -> Largesse
    """
    from urllib.parse import urlparse
    import os

    fname = os.path.basename(urlparse(u).path)
    name = os.path.splitext(fname)[0]
    return name.replace("-", " ").title()


def extract_text(image):
    """Perform OCR on a PIL image and return the recognized text.

    This helper is separated from the scraping logic so it can be reused if
    image‑to‑text functionality is required elsewhere.
    """
    try:
        import pytesseract
        return pytesseract.image_to_string(image).strip()
    except Exception as e:
        print(f"OCR error: {e}")
        return ""


def extract_mappings(results: list[dict], filepath: str) -> None:
    """Write a name->tier mapping file from scraper results.

    * ``results`` should come from :func:`scrape_images`.
    * ``filepath`` is the path where the mapping text will be written.

    The file format is one mapping per line, using the pattern
    ``'Card Name'=>'T'`` where ``T`` is the tier letter.  Existing files
    are overwritten.  The card name is determined by parsing the image URL
    (hyphens are converted to spaces and the result is title-cased).
    """
    with open(filepath, "w", encoding="utf-8") as f:
        for entry in results:
            url = entry.get("url")
            tier = entry.get("tier", "").upper()
            if not url or not tier:
                continue
            name = _name_from_url(url)
            f.write(f"'{name}'=>'{tier}'\n")


def load_mappings(filepath: str) -> list[dict]:
    """Load a mapping file produced by :func:`extract_mappings`.

    Returns a list of dicts containing at least ``"name"`` and ``"tier"``.
    Lines that do not match the expected pattern are ignored.
    """
    results: list[dict] = []
    import re

    pattern = re.compile(r"'(?P<name>[^']+)'\s*=>\s*'?(?P<t>[SABCD])'?")
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            m = pattern.search(line)
            if not m:
                continue
            results.append({"name": m.group("name"), "tier": m.group("t")})
    return results



if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrape card images and optionally search by tier."
    )
    parser.add_argument(
        "--search",
        metavar="TIER",
        help="show card names for the given tier letter (S/A/B/C/D)",
    )
    parser.add_argument(
        "--save",
        metavar="DIR",
        help="directory under which to download images organized by champion/tier",
    )
    parser.add_argument(
        "--map",
        metavar="FILE",
        help="write card name->tier mappings to FILE",
    )
    parser.add_argument(
        "--name",
        metavar="CARD",
        help="look up a card by name and display its tier",
    )
    args = parser.parse_args()

    # load data either via mapping file or network (for map/save generation)
    cards: list[dict] = []
    if args.map:
        if args.save or not os.path.exists(args.map):
            page = "https://mobalytics.gg/slay-the-spire-2/tier-lists/cards"
            cards = scrape_images(page, save_root=args.save) if args.save else scrape_images(page)
            extract_mappings(cards, args.map)
            cards = load_mappings(args.map)
        else:
            cards = load_mappings(args.map)
    elif args.save:
        page = "https://mobalytics.gg/slay-the-spire-2/tier-lists/cards"
        cards = scrape_images(page, save_root=args.save)
    else:
        print("no mappings file specified; run with --map or --save first")

    def name_from_url(u: str) -> str:
        from urllib.parse import urlparse
        import os

        fname = os.path.basename(urlparse(u).path)
        name = os.path.splitext(fname)[0]
        return name.replace("-", " ").title()

    if args.search:
        tier_letter = args.search.strip().upper()
        for entry in cards:
            if entry.get("tier", "").upper() == tier_letter:
                # mapping entries may have 'name'
                print(entry.get("name", entry.get("url", "")))
    elif args.name:
        target = args.name.strip().lower()
        found = False
        for entry in cards:
            cardname = entry.get("name", "").lower()
            if cardname == target:
                print(entry.get("tier", "?"))
                found = True
                break
        if not found:
            print(f"'{args.name}' not found")
    else:
        for entry in cards:
            if "name" in entry:
                line = entry["name"]
            else:
                line = entry.get("url", "")
            tier = entry.get("tier", "?")
            print(f"[{tier}] {line}")