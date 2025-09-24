"""
Streamlit app for scraping Kleinanzeigen ads
-------------------------------------------

This web application allows you to paste or upload a list of Kleinanzeigen
classified ads and extract structured information about wheels and tyres.
Under the hood it uses the functions defined in scraper.py to perform
the scraping.  After processing all ads, the app displays the resulting
table and offers download buttons for both the CSV file and a ZIP archive
containing all downloaded images.

To run this app locally, install the required dependencies (see
requirements.txt) and execute:

    streamlit run app.py

You can also deploy the app on Streamlit Cloud or any other hosting platform
that supports Streamlit.
"""

import io
import zipfile
from pathlib import Path
from typing import List

import pandas as pd
import streamlit as st

from scraper import scrape_urls, Listing


def make_zip_of_images(image_paths: List[str], base_dir: Path) -> bytes:
    """Create a ZIP archive in memory from a list of image paths.

    Parameters
    ----------
    image_paths : list of str
        The relative paths to images inside base_dir to include in the archive.
    base_dir : Path
        The base directory relative to which the paths are defined.

    Returns
    -------
    bytes
        The contents of the ZIP archive.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel_path in image_paths:
            abs_path = base_dir / rel_path
            if abs_path.exists():
                zf.write(abs_path, arcname=rel_path)
    buffer.seek(0)
    return buffer.read()


st.set_page_config(page_title="Kleinanzeigen Felgen/Kompletträder Scraper",
                   layout="wide")
st.title("Kleinanzeigen Felgen/Kompletträder Scraper")
st.markdown(
    """
    Geben Sie eine Liste von Kleinanzeigen‑Links ein (eine URL pro Zeile) oder
    laden Sie eine Textdatei hoch.  Nach dem Start werden alle Inserate
    automatisch besucht, die relevanten Daten extrahiert und die Bilder
    heruntergeladen.  Anschließend können Sie die Daten als CSV sowie alle
    Bilder als ZIP herunterladen.
    """
)

# Input for URLs
urls_text = st.text_area("Inserat‑Links (eine pro Zeile)", height=200)
uploaded_file = st.file_uploader("oder Textdatei mit Links hochladen", type=["txt"])

if uploaded_file is not None:
    file_content = uploaded_file.read().decode("utf-8")
    urls_text = file_content

urls = [url.strip() for url in urls_text.splitlines() if url.strip()]

if st.button("Scrapen"):
    if not urls:
        st.warning("Bitte geben Sie mindestens einen Link ein.")
    else:
        with st.spinner("Scraping läuft – bitte warten..."):
            # Use a temporary directory inside the current working directory
            output_dir = Path("scraped_output")
            # Perform scraping
            records: List[Listing] = scrape_urls(urls, out_dir=str(output_dir), csv_filename="data.csv")
            # Convert records to DataFrame
            if records:
                df = pd.DataFrame([rec.as_csv_row() for rec in records])
                st.success(f"{len(records)} Inserate erfolgreich verarbeitet!")
                st.dataframe(df, use_container_width=True)
                # Provide download links
                # CSV
                csv_bytes = df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="CSV herunterladen",
                    data=csv_bytes,
                    file_name="data.csv",
                    mime="text/csv",
                )
                # Images ZIP
                # Collect all image paths from all records
                all_images = []
                for rec in records:
                    all_images.extend(rec.image_files)
                if all_images:
                    zip_bytes = make_zip_of_images(all_images, output_dir)
                    st.download_button(
                        label="Bilder als ZIP herunterladen",
                        data=zip_bytes,
                        file_name="images.zip",
                        mime="application/zip",
                    )
                else:
                    st.info("Keine Bilder zum Herunterladen gefunden.")
            else:
                st.error("Es wurden keine Daten extrahiert.")
