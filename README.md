Kleinanzeigen Felgen/Kompletträder Scraper
==========================================

Dieses Repository enthält einen Python‑Scraper und eine dazugehörige
Streamlit‑Webanwendung zum Extrahieren von Daten aus Inseraten auf
kleinanzeigen.de (ehemals eBay Kleinanzeigen).  Mit diesem Tool können Sie
beliebig viele Anzeigen über ihre URLs einspeisen, sämtliche relevanten
Informationen (Felgenhersteller, Reifenhersteller, Größen, Lochkreis, ET
usw.) herausziehen und alle Inseratsbilder herunterladen.  Die Ergebnisse
können als CSV exportiert werden, während die Bilder als ZIP zur Verfügung
stehen, um sie zusammen mit der CSV auf Ihrer eigenen Seite hochzuladen.

### Dateien

* `scraper.py` – Das Herzstück des Projekts.  Enthält Funktionen zum
  Herunterladen einzelner Anzeigen, Parsen der HTML‑Seiten, Extraktion und
  strukturierten Aufbereitung der Daten sowie das Speichern der Bilder.
* `app.py` – Ein Streamlit‑Frontend, das eine einfache Benutzeroberfläche
  bietet, um eine Liste von Inserat‑Links einzulesen, die Scraping‑Routine zu
  starten und anschließend die Ergebnisse als CSV bzw. ZIP herunterzuladen.
* `requirements.txt` – Abhängigkeiten, die für das Projekt benötigt
  werden.  Installieren Sie diese am besten in einer virtuellen Umgebung mit
  `pip install -r requirements.txt`.
* `README.md` – Diese Datei.

### Verwendung

**Lokaler Scraper (Kommandozeile)**

1. Erstellen Sie eine Textdatei `urls.txt` mit jeweils einer Kleinanzeigen‑URL
   pro Zeile.  Beispiel:

   ```
   https://www.kleinanzeigen.de/s-anzeige/beispiel-inserat-1/1234567890-223-1234
   https://www.kleinanzeigen.de/s-anzeige/beispiel-inserat-2/1234567891-223-1234
   ```

2. Installieren Sie die Abhängigkeiten und führen Sie anschließend den
   Scraper aus:

   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   python scraper.py
   ```

3. Nach dem Durchlauf befinden sich im Ordner `output` eine `data.csv` sowie
   Unterordner mit den heruntergeladenen Bildern.  Jeder Unterordner ist nach
   der Anzeigen‑ID benannt, und die CSV enthält relative Bildpfade.

**Streamlit‑Anwendung**

1. Installieren Sie wie oben die Abhängigkeiten.
2. Starten Sie die Anwendung mit `streamlit run app.py`.
3. Fügen Sie im Browser die gewünschten Inserat‑Links (eine pro Zeile) ein
   oder laden Sie eine Textdatei hoch.  Betätigen Sie den Button „Scrapen“.
4. Nach erfolgreichem Durchlauf wird eine Vorschautabelle angezeigt.
5. Über die Download‑Buttons können Sie die generierte CSV und ein ZIP mit
   allen Bildern herunterladen.

### Hinweise

* Der Scraper respektiert die Anforderungen der User‑Agents, indem er beim
  Abruf der Seiten einen gängigen Browser‑String sendet.
* Da Anzeigen unterschiedlich gestaltet werden können, basiert die Erkennung
  vieler Informationen auf heuristischen Regeln und regulären Ausdrücken.
  Sollten bestimmte Felder nicht gefunden werden, wird ein Platzhalter `/` in
  die CSV eingetragen.
* Die Bild‑Links werden anhand der `<img>`‑Tags der Seite gesammelt.  Die
  Query‑Parameter (z. B. `?rule=$\_2.JPG`) werden entfernt, um die bestmögliche
  Auflösung zu laden.
* Für die Verarbeitung einer großen Anzahl von Anzeigen empfiehlt es sich,
  nicht zu viele Anfragen gleichzeitig abzusetzen, um die Server von
  kleinanzeigen.de nicht zu überlasten.  Der Scraper arbeitet sequenziell
  und kann bei Bedarf durch eigene Anpassungen mit Wartezeiten versehen
  werden.

Viel Erfolg beim Scrapen!
