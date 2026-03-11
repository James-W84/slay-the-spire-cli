# spire2

`spire2` is a command–line tool for querying Slay the Spire 2 card tier
lists. Internally it scrapes the Mobalytics tier list page, caches the
results in `~/.spire2/` and allows fast lookups by card name or tier. The
user experience is "zero‑config": after installing the package nothing else
needs to be specified.

The project is structured as an installable Python package with an entry
tool; the original standalone script has been retained only as a thin
compatibility wrapper.

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

> **Supported content**: this tool only works with Slay the Spire 2 cards for
> the three champions currently covered by the tier lists – the Watcher (also
> known as the Regent on the site), the Silent and the Ironclad. Other
> champions are not available and will not be found in the mapping file.

## Usage

Install the package (editable mode during development):

```sh
pip install -e .
```

An executable named `spire2` will be placed on your `PATH`. The first time
you run any command the tool will fetch and cache the tier list data; this
happens automatically and is transparent to the user.

```sh
spire2 --name "Photon Cut"   # first run will display a setup message
spire2 --search A            # list all cards in tier A
spire2 --name "Celestial Might"
```

Subsequent invocations use the local cache and return instantly. The cached
mappings are automatically refreshed every three days.

If you prefer the legacy script instead of the package entry point you can
still run:

```sh
python sts2tierlistscraper.py --name "Photon Cut"
```

### Generating data

```sh
# scrape the site, download images into `tier_images/`, and write mapping to file
sts --save tier_images --map mappings.txt
# or equivalently:
python sts2tierlistscraper.py --save tier_images --map mappings.txt
```

The mapping file will look like:

```
'Adrenaline'=>'S'
'Big Bang'=>'S'
'Gamma Blast'=>'A'
...
```

### Querying

By default `spire2` uses a mappings file at `~/.spire2/mappings.txt` which is
maintained automatically; you should not need to pass `--map` or deal with
paths. Nevertheless the old options remain available for power users or
development:

```sh
spire2 --search A            # show all cards in tier A
spire2 --name "Celestial Might"  # display tier for a particular card
spire2 --save ~/cards/          # download tiered images
spire2 --map /tmp/foo.txt       # override the mappings location
```

The `--save` flag still behaves as before, writing images organised by
champion and tier.

### Advanced / Development

The package's core logic lives in `spire2_pkg/main.py`. The legacy
`sts2tierlistscraper.py` file now simply wraps this module and is provided
for backwards compatibility; new development should target the package
itself.

Existing helper functions such as `scrape_images`, `extract_mappings` and
`load_mappings` are available for reuse in scripts or tests.

## License

None

## Development

The core scraping logic is in `sts2tierlistscraper.py`. You can extend it or
reuse the helper functions (`scrape_images`, `extract_mappings`,
`load_mappings`).

Be mindful that the target page is heavy on JavaScript; the parser relies on
static HTML structures and the JSON blob present on initial page load. If
the site changes, the selectors may need updating.

## License

None
