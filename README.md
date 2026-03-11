# Slay the Spire Tier List Scraper

This small Python utility scrapes card images from the Mobalytics Slay the
Spire 2 tier list page and helps you organise, map and query them by tier.
It is designed for offline lookups after the initial data has been collected.

## Features

- Download tiered card images, organised by champion (Regent, Ironclad,
  Silent) and tier (`S` through `D`).
- Generate a simple mapping file that associates each card name with a tier
  letter.
- Command‑line lookup of cards by tier or by name using the mapping file.
- Optional OCR helper for future image‑to‑text work.

## Requirements

- Python 3.9+
- `requests`, `beautifulsoup4` (installed via `pip install -r requirements.txt` or
  individually)

## Usage

Run the script from the repository root.

### Generating data

```sh
# scrape the site, download images into `tier_images/`, and write mapping to file
python sts2tierlistscraper.py --save tier_images --map mappings.txt
```

The mapping file will look like:

```
'Adrenaline'=>'S'
'Big Bang'=>'S'
'Gamma Blast'=>'A'
...
```

Once you have `mappings.txt`, you no longer need a network connection for
lookups.

### Querying

```sh
# list all cards in tier A
python sts2tierlistscraper.py --map mappings.txt --search A

# look up a specific card
python sts2tierlistscraper.py --map mappings.txt --name "Largesse"
```

If you only run with `--map` the script will load the file and skip any
network activity unless the file is missing or `--save` is also provided.

### Other options

- `--map FILE` : path to mapping file to read/write
- `--save DIR` : root directory to store downloaded card images
- `--search TIER` : show card names for specified tier letter
- `--name CARD` : lookup tier for specified card name

## Development

The core scraping logic is in `sts2tierlistscraper.py`. You can extend it or
reuse the helper functions (`scrape_images`, `extract_mappings`,
`load_mappings`).

Be mindful that the target page is heavy on JavaScript; the parser relies on
static HTML structures and the JSON blob present on initial page load. If
the site changes, the selectors may need updating.

## License

None
