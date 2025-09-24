"""
scraper.py
This module provides functionality to scrape vehicle‑wheel classified ads from
Kleinanzeigen.  The goal of the scraper is to accept a list of ad URLs,
download every page, extract all available information (title, description,
specifications, price and location) and parse that unstructured text into a
structured format ready for CSV export.  All images associated with each
listing are downloaded into a dedicated subdirectory, and the relative
filenames are stored in the CSV so that they can later be uploaded alongside
the tabular data.

The parser makes a best effort to pull the desired fields from the freeform
text.  It uses a combination of regular expressions and keyword lookups to
guess values for:

    * Felgenhersteller (wheel manufacturer)
    * Felgenfarbe (wheel colour)
    * Zollgröße (wheel diameter in inches)
    * Zollbreite Vorderachse / Hinterachse (rim width front/rear)
    * Lochkreis (bolt pattern)
    * Nabendurchmesser (hub bore)
    * Einpresstiefe (offset, ET)
    * Reifenhersteller (tyre manufacturer)
    * Reifensaison (season: Winter, Sommer, Ganzjahr)
    * Reifengröße Vorderachse / Hinterachse (tyre size front/rear)
    * Reifenbreite Vorderachse / Hinterachse (tyre width front/rear)
    * Reifenprofil Vorderachse / Hinterachse (aspect ratio front/rear)
    * Reifenhöhe Vorderachse / Hinterachse (rim diameter in inches front/rear)
    * DOT Vorderachse / Hinterachse (tyre manufacturing date codes)
    * Preis (price in EUR)

If certain information cannot be determined from the page, the scraper fills
the corresponding column with a placeholder “/” as requested.  Since
Kleinanzeigen pages can change their HTML structure at any time, and since
publishers can write arbitrary descriptions, the extraction heuristics are not
perfect.  They work best for typical wheel/tyre ads but will gracefully fall
back to placeholders when data cannot be found.

Usage:

    from scraper import scrape_urls

    urls = ["https://www.kleinanzeigen.de/s-anzeige/...", ...]
    records = scrape_urls(urls, out_dir="data")
    # records is a list of dictionaries suitable for conversion to a DataFrame

When run as a script, scraper.py expects a plain text file `urls.txt` in
the current directory containing one Kleinanzeigen ad URL per line.  It
creates an `output` directory with downloaded images and writes
`output/data.csv` containing the scraped dataset.
"""

from __future__ import annotations

import csv
import json
import os
import re
import urllib.parse
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable, List, Dict, Tuple, Optional

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Helper dataclass representing a single scraped listing.  Storing the data
# separately from the parsing logic makes it easy to convert to dict/CSV.
# ---------------------------------------------------------------------------
@dataclass
class Listing:
    url: str
    title: str = "/"
    location: str = "/"
    description: str = ""
    price: str = "/"
    felgenhersteller: str = "/"
    felgenfarbe: str = "/"
    zollgroesse: str = "/"
    zollbreite_vorne: str = "/"
    zollbreite_hinten: str = "/"
    lochkreis: str = "/"
    nabendurchmesser: str = "/"
    einpresstiefe: str = "/"
    reifenhersteller: str = "/"
    reifensaison: str = "/"
    reifengroesse_vorne: str = "/"
    reifenbreite_vorne: str = "/"
    reifenprofil_vorne: str = "/"
    reifenhoehe_vorne: str = "/"
    dot_vorne: str = "/"
    reifengroesse_hinten: str = "/"
    reifenbreite_hinten: str = "/"
    reifenprofil_hinten: str = "/"
    reifenhoehe_hinten: str = "/"
    dot_hinten: str = "/"
    image_files: List[str] = field(default_factory=list)

    def as_csv_row(self) -> Dict[str, str]:
        """Return a dict ready to be written as a CSV row."""
        row = asdict(self)
        # Join multiple image filenames into a single string separated by | to
        # preserve multiple images in one cell.  When there are no images the
        # column will contain an empty string.
        row["image_files"] = "|".join(self.image_files) if self.image_files else "/"
        return row


# ---------------------------------------------------------------------------
# Regular expressions and lookup tables used to parse unstructured text.
# These are compiled once and reused during scraping.
# ---------------------------------------------------------------------------
# Recognised tyre manufacturers.  Feel free to extend this list as required.
TYRE_MANUFACTURERS = [
    "MICHELIN", "CONTINENTAL", "DUNLOP", "PIRELLI", "GOODYEAR", "HANKOOK",
    "BRIDGESTONE", "FALKEN", "NOKIAN", "TOYO", "YOKOHAMA", "VREDESTEIN",
    "SEMPERIT", "KLEBER", "NEXEN", "UNIROYAL", "BF GOODRICH", "BARUM",
    "MATADOR", "KUMHO", "TRACMAX", "SAVA", "MAXXIS", "LINGLONG", "SUNNY",
]
# Recognised wheel manufacturers.  This list is deliberately non‑exhaustive.
WHEEL_MANUFACTURERS = [
    "BBS", "OZ", "BORBET", "RIAL", "ATS", "ALUTEC", "DEZENT", "MAK",
    "MAM", "AEZ", "RC DESIGN", "ALPINA", "AMG", "RONAL", "SCHMIDT",
    "BROCK", "RONDELL", "DOTZ", "MTM", "RH", "MSW", "VOSSEN", "ENKEI",
    "ADVANTI", "WORK", "HRE", "SPEEDLINE", "AUTEC",
]
# Recognised colours (German names).  Both lowercase and capitalised entries
# are matched in a case‑insensitive manner.
COLOURS = [
    "SCHWARZ", "SCHWARZ MATT", "SILBER", "SILBERN", "GRAU", "GRAU MATT",
    "ANTHRAZIT", "ANTHRAZIT MATT", "WEISS", "WEIß", "CHROM", "POLIERT",
    "BRONZE", "GOLD", "GUNMETAL", "GRAPHIT", "TITAN", "SCHWARZ GLANZ",
]
# Regex patterns for various metrics.
RE_ZOLL = re.compile(r"(\d{1,2})\s*ZOLL", re.IGNORECASE)
RE_R = re.compile(r"R\s*(\d{2})", re.IGNORECASE)
RE_WIDTH_DIAM = re.compile(r"(\d{1,2}[,\.]?\d?)\s*[jx×xX]\s*(\d{1,2})", re.IGNORECASE)
RE_LOCHKREIS = re.compile(r"(\d)\s*[x×/]\s*(\d{2,3})", re.IGNORECASE)
RE_LOCHKREIS_SIMPLE = re.compile(r"(\d)\s*[x×/]\s*(\d{2,3})", re.IGNORECASE)
RE_OFFSET = re.compile(r"(?:ET|EINPRESSTIEFE)\s*[:]?\s*(\d{1,3})", re.IGNORECASE)
RE_HUB = re.compile(r"(?:NABEN(?:BOHRUNG|DURCHMESSER)?|ZENTRIERUNG)\s*[:]?\s*(\d{2,3}[,.]?\d?)", re.IGNORECASE)
RE_REIFEN = re.compile(r"(\d{3})\s*/\s*(\d{2})\s*(?:R|ZR)?\s*(\d{2})", re.IGNORECASE)
RE_DOT = re.compile(r"DOT\s*[:\-]?\s*(\d{4})", re.IGNORECASE)
RE_PRICE = re.compile(r"([\d\.]+,\d{2}|\d{1,3}(?:\.\d{3})*)\s*€")


def normalise_text(text: str) -> str:
    """Return text with normalised whitespace and without excessive line breaks."""
    return re.sub(r"\s+", " ", text.strip())


def parse_manufacturer(text: str, manufacturers: List[str]) -> Optional[str]:
    """Return the first manufacturer from the list found in the text.

    The search is case‑insensitive.  Spaces in manufacturer names are
    ignored when matching to allow e.g. "BF Goodrich" to match "BFGOODRICH".
    """
    text_upper = text.upper().replace(" ", "")
    for manu in manufacturers:
        if manu.replace(" ", "") in text_upper:
            return manu
    return None


def parse_colour(text: str) -> Optional[str]:
    """Return the first recognised colour from the list found in the text."""
    text_upper = text.upper()
    for colour in COLOURS:
        if colour in text_upper:
            return colour.title()  # return capitalised version
    return None


def parse_zollgroesse(text: str) -> Optional[str]:
    """Extract the wheel diameter (in inches) from the text.

    Attempts to match patterns like "19 Zoll" or "R19".  Returns the first match found.
    """
    m = RE_ZOLL.search(text)
    if m:
        return m.group(1)
    m = RE_R.search(text)
    if m:
        return m.group(1)
    return None


def parse_widths(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract rim widths (front and rear) from patterns like "8.5Jx19" or "9x20".

    If only one width is present, it is returned for both front and rear.  If two
    widths are found (e.g. "8.5Jx19 vorne, 9.5Jx19 hinten") then the first
    corresponds to the front axle and the second to the rear axle.
    """
    matches = RE_WIDTH_DIAM.findall(text.replace("\u00a0", " "))
    if not matches:
        return None, None
    # We only care about the width (first capture group).  The diameter is parsed
    # separately via parse_zollgroesse.
    widths = [m[0].replace(",", ".") for m in matches]
    if len(widths) == 1:
        return widths[0], widths[0]
    # If there are two or more widths take the first two
    return widths[0], widths[1]


def parse_bolt_pattern(text: str) -> Optional[str]:
    """Extract the bolt pattern (e.g. "5x112" or "5/112") from the text.

    Bolt patterns may be written with 'x', '×' or '/' separators, optionally
    preceded by the abbreviation 'LK' (Lochkreis).  The returned pattern
    normalises the separator to 'x'.
    """
    # Look for the term "LK" or "Lochkreis" followed by numbers separated by '/' or 'x'
    lk_match = re.search(r"(?:LK|LOCHKREIS)\s*(\d)\s*[x×/]\s*(\d{2,3})", text, re.IGNORECASE)
    if lk_match:
        return f"{lk_match.group(1)}x{lk_match.group(2)}"
    # Generic fallback: match patterns like '5x112' where the second group has three digits (typical PCD)
    generic = re.search(r"\b([3-9])\s*[x×/]\s*(\d{3})\b", text)
    if generic:
        return f"{generic.group(1)}x{generic.group(2)}"
    return None


def parse_offset(text: str) -> Optional[str]:
    """Extract the ET (offset) value from the text."""
    m = RE_OFFSET.search(text)
    if m:
        return m.group(1)
    return None


def parse_hub(text: str) -> Optional[str]:
    """Extract the hub bore (Nabendurchmesser) from the text."""
    m = RE_HUB.search(text)
    if m:
        return m.group(1).replace(",", ".")
    return None


def parse_tyre_sizes(text: str) -> Tuple[List[Tuple[str, str, str]], List[str]]:
    """Extract all tyre sizes and DOT codes from the text.

    Returns a list of tuples (width, profile, diameter) and a list of DOT
    codes.  The caller decides how to map the first and second items to
    front/rear axles.
    """
    sizes = RE_REIFEN.findall(text)
    dots = RE_DOT.findall(text)
    # Convert tuples of strings into lists of strings as is
    return sizes, dots


def parse_price(text: str) -> Optional[str]:
    """Extract the price from the text.  Returns the price string without €.

    European prices can contain thousands separators (.) and decimal comma (,).
    This function preserves the comma and dot for later formatting by the caller.
    """
    m = RE_PRICE.search(text)
    if m:
        return m.group(1)
    return None


def extract_ld_json(soup: BeautifulSoup) -> Optional[Dict]:
    """Return the first JSON object embedded in a <script type="application/ld+json"> tag.

    Many Kleinanzeigen pages include structured data in JSON‑LD format which
    contains address information and sometimes price data.  We parse the first
    such block and return it as a dict.  If parsing fails the function
    returns None.
    """
    scripts = soup.find_all('script', type='application/ld+json')
    for script in scripts:
        try:
            data = json.loads(script.string)
            return data
        except Exception:
            continue
    return None


def extract_location_from_ld(data: Dict) -> Optional[str]:
    """Extract a human‑readable location from the JSON‑LD structure."""
    # The structure can vary; attempt to traverse typical fields
    try:
        if isinstance(data, list):
            # Sometimes ld+json is an array
            for entry in data:
                loc = extract_location_from_ld(entry)
                if loc:
                    return loc
        if '@type' in data and data.get('@type') in ('Offer', 'Product', 'NewsArticle', 'Event', 'Service'):
            if 'availableAtOrFrom' in data and 'address' in data['availableAtOrFrom']:
                addr = data['availableAtOrFrom']['address']
                parts = [addr.get(k) for k in ('streetAddress','postalCode','addressLocality','addressRegion') if addr.get(k)]
                if parts:
                    return ', '.join(parts)
            if 'areaServed' in data and 'name' in data['areaServed']:
                return data['areaServed']['name']
            if 'seller' in data and isinstance(data['seller'], dict):
                # professional seller address
                addr = data['seller'].get('address', {})
                parts = [addr.get(k) for k in ('streetAddress','postalCode','addressLocality','addressRegion') if addr.get(k)]
                if parts:
                    return ', '.join(parts)
    except Exception:
        pass
    return None


def extract_images(soup: BeautifulSoup, base_url: str) -> List[str]:
    """Find all image URLs in the page.

    The function looks for <img> tags whose source points to the Kleinanzeigen
    image CDN.  Duplicate URLs are removed and query parameters are stripped
    so that high‑resolution images are downloaded whenever possible.
    """
    imgs = set()
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
        if not src:
            continue
        # Only accept Kleinanzeigen image hosts
        if 'img.kleinanzeigen.de' in src:
            # Remove query parameters (e.g. ?rule=$_2.JPG) to get full size
            clean = src.split('?')[0]
            imgs.add(clean)
    # Sometimes the image URLs are relative; make them absolute
    result = []
    for url in imgs:
        if url.startswith('http'):
            result.append(url)
        else:
            result.append(urllib.parse.urljoin(base_url, url))
    return sorted(result)


def parse_listing(url: str, out_dir: Path) -> Listing:
    """Download and parse a single Kleinanzeigen ad.

    Creates a Listing object containing structured data and downloads all
    associated images into the directory specified by out_dir.  Image filenames
    are stored relative to out_dir and returned in the Listing.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/115.0 Safari/537.36"
    }
    # Retrieve the web page
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    listing = Listing(url=url)
    # Title
    title_el = soup.find(['h1','h2'], string=True)
    if title_el:
        listing.title = normalise_text(title_el.get_text())

    # Attempt to extract location and price via JSON‑LD
    ld_data = extract_ld_json(soup)
    if ld_data:
        loc = extract_location_from_ld(ld_data)
        if loc:
            listing.location = normalise_text(loc)
        # Price might be present
        try:
            price_dict = ld_data.get('offers', ld_data.get('offer', None))
            if isinstance(price_dict, dict):
                amount = price_dict.get('price') or price_dict.get('priceSpecification', {}).get('price')
                currency = price_dict.get('priceCurrency', 'EUR')
                if amount:
                    listing.price = f"{amount} {currency}"
        except Exception:
            pass

    # Fallback: try to find a span with € sign for price
    if listing.price == "/":
        price_tag = soup.find(string=re.compile(r"€"))
        if price_tag:
            price_match = RE_PRICE.search(price_tag if isinstance(price_tag, str) else price_tag.get_text())
            if price_match:
                listing.price = price_match.group(1)

    # Description – ads may have the description in a <pre>, <div> or other container
    desc_parts = []
    # Try known selectors
    desc_selectors = [
        {"name": "div", "attrs": {"data-testid": "description"}},
        {"name": "div", "attrs": {"class": re.compile(r"description")}},
        {"name": "pre"},
    ]
    for sel in desc_selectors:
        el = soup.find(**sel)
        if el:
            desc_parts.append(el.get_text(separator="\n"))
    if not desc_parts:
        # fallback: all paragraph texts
        paragraphs = [p.get_text() for p in soup.find_all('p')]
        desc_parts.extend(paragraphs)
    description = normalise_text("\n".join(desc_parts))
    listing.description = description

    # Build a combined text field from title and description for parsing
    combined_text = f"{listing.title}\n{listing.description}"

    # Parse manufacturer names
    manu = parse_manufacturer(combined_text, WHEEL_MANUFACTURERS)
    if manu:
        listing.felgenhersteller = manu
    tyre_manu = parse_manufacturer(combined_text, TYRE_MANUFACTURERS)
    if tyre_manu:
        listing.reifenhersteller = tyre_manu

    # Parse colour
    colour = parse_colour(combined_text)
    if colour:
        listing.felgenfarbe = colour

    # Parse wheel diameter (Zollgröße)
    zoll = parse_zollgroesse(combined_text)
    if zoll:
        listing.zollgroesse = zoll

    # Parse rim widths
    width_front, width_rear = parse_widths(combined_text)
    if width_front:
        listing.zollbreite_vorne = width_front
    if width_rear:
        listing.zollbreite_hinten = width_rear

    # Parse bolt pattern
    bolt = parse_bolt_pattern(combined_text)
    if bolt:
        listing.lochkreis = bolt

    # Parse hub bore
    hub = parse_hub(combined_text)
    if hub:
        listing.nabendurchmesser = hub

    # Parse offset
    offset = parse_offset(combined_text)
    if offset:
        listing.einpresstiefe = offset

    # Parse tyre sizes and DOTs
    sizes, dots = parse_tyre_sizes(combined_text)
    if sizes:
        # if there are two sizes assign to front and rear; otherwise use same
        front_size = sizes[0]
        listing.reifengroesse_vorne = "/".join(front_size)
        listing.reifenbreite_vorne = front_size[0]
        listing.reifenprofil_vorne = front_size[1]
        listing.reifenhoehe_vorne = front_size[2]
        if len(sizes) > 1:
            rear_size = sizes[1]
            listing.reifengroesse_hinten = "/".join(rear_size)
            listing.reifenbreite_hinten = rear_size[0]
            listing.reifenprofil_hinten = rear_size[1]
            listing.reifenhoehe_hinten = rear_size[2]
        else:
            listing.reifengroesse_hinten = listing.reifengroesse_vorne
            listing.reifenbreite_hinten = listing.reifenbreite_vorne
            listing.reifenprofil_hinten = listing.reifenprofil_vorne
            listing.reifenhoehe_hinten = listing.reifenhoehe_vorne

    # Assign DOT codes if present
    if dots:
        listing.dot_vorne = dots[0]
        if len(dots) > 1:
            listing.dot_hinten = dots[1]
        else:
            listing.dot_hinten = dots[0]

    # Determine tyre season
    text_upper = combined_text.upper()
    if "WINTERREIF" in text_upper:
        listing.reifensaison = "Winter"
    elif "SOMMERREIF" in text_upper:
        listing.reifensaison = "Sommer"
    elif "GANZJAHR" in text_upper or "ALLWETTER" in text_upper:
        listing.reifensaison = "Ganzjahres"

    # Download images
    images = extract_images(soup, url)
    listing.image_files = []
    if images:
        # Create subdirectory for this ad
        ad_id = None
        # Try to extract numeric ID from URL (last segment before dash may contain the ID)
        m = re.search(r"/(\d{7,10})", url)
        if m:
            ad_id = m.group(1)
        else:
            # fallback: use index based on number of existing dirs
            ad_id = str(len(list(out_dir.iterdir())))
        ad_dir = out_dir / ad_id
        ad_dir.mkdir(parents=True, exist_ok=True)
        for idx, img_url in enumerate(images):
            try:
                img_resp = requests.get(img_url, headers=headers, timeout=30)
                img_resp.raise_for_status()
                suffix = Path(urllib.parse.urlparse(img_url).path).suffix
                # Ensure suffix is valid; default to .jpg
                if not suffix or len(suffix) > 5:
                    suffix = '.jpg'
                filename = f"{idx+1}{suffix}"
                file_path = ad_dir / filename
                with open(file_path, 'wb') as f:
                    f.write(img_resp.content)
                listing.image_files.append(str(file_path.relative_to(out_dir)))
            except Exception:
                # Ignore download failures; continue with next image
                continue

    return listing


def scrape_urls(urls: Iterable[str], out_dir: str = "output",
                csv_filename: str = "data.csv") -> List[Listing]:
    """Scrape a list of Kleinanzeigen ad URLs into a structured CSV.

    Parameters
    ----------
    urls : Iterable[str]
        A sequence of Kleinanzeigen ad URLs.
    out_dir : str
        Directory where images and the CSV file will be saved.  If the
        directory does not exist it will be created.
    csv_filename : str
        Name of the CSV file to create inside out_dir.

    Returns
    -------
    List[Listing]
        A list of Listing objects representing the scraped ads.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    records: List[Listing] = []
    for i, url in enumerate(urls):
        url = url.strip()
        if not url:
            continue
        try:
            print(f"[{i+1}/{len(urls)}] Scraping {url}")
            record = parse_listing(url, out_path)
            records.append(record)
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            continue
    # Write CSV
    if records:
        csv_path = out_path / csv_filename
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(records[0].as_csv_row().keys()))
            writer.writeheader()
            for rec in records:
                writer.writerow(rec.as_csv_row())
        print(f"Saved data to {csv_path}")
    return records


def main():
    """Entry point for command line usage."""
    urls_file = Path('urls.txt')
    if not urls_file.exists():
        print("Please create a file named 'urls.txt' with one Kleinanzeigen URL per line.")
        return
    with open(urls_file, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip()]
    scrape_urls(urls)


if __name__ == '__main__':
    main()