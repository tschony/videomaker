# Velvet Video Maker

Lokale Mac-Web-App fuer Velvet-Meridian-Longform-Produktionen.

## Start

```bash
cd videomaker
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8787
```

Danach im Browser oeffnen:

```text
http://127.0.0.1:8787
```

Wichtig: Die App muss fuer native macOS-Finder-Dialoge und lokale Renderjobs
auf dem Mac laufen. Eine Vercel-/Cloud-URL kann keine lokalen Ordner im Finder
oeffnen und hat keinen Zugriff auf lokale WAVs, MP4s oder `ffmpeg` auf deinem
Mac.

Optional kann die Velvet-Meridian-Projektwurzel gesetzt werden:

```bash
export VELVET_PROJECT_ROOT="/Users/jrkavrazli/Documents/Projekte/Music_Publishment"
```

## Aktueller Umfang

- Dry-Run fuer WAV- und Bild-Erkennung.
- Bilder werden im Source-Ordner automatisch nach Format erkannt und zugeordnet:
  bestes 16:9-Bild fuer Longform, bestes 9:16-Bild fuer Shorts. Manuelle
  Auswahl ist nur noetig, wenn kein passendes Bild gefunden wird oder ein
  anderes Bild gewuenscht ist.
- `Browse` oeffnet den nativen macOS-Finder-Dialog fuer Source Folder, Output
  Folder und Bildpfade.
- Neue Ausgabeordner koennen direkt im nativen Output-Folder-Dialog angelegt
  werden; der interne Ordnerbrowser bleibt als Fallback erhalten.
- Der gewaehlte Output Folder ist ein Basisordner. Pro Render wird automatisch
  ein Unterordner aus `COMP-ID_Titel` angelegt, z. B.
  `.../Compilations/VM_COMP072_Oracle_of_Delphi_Call_Center_Lounge`.
- Nach erfolgreichem Render und Medienvalidierung werden die Original-WAVs per
  `shutil.move()` nach `sources/original/` im COMP-Ordner verschoben und nach
  `COMP_ID_SRC##_Titel_Suno-ID.wav` umbenannt. JSON-Sidecars gehen nach
  `sources/json/`.
- Die verwendeten 16:9- und 9:16-Bilder werden nach erfolgreichem Render nach
  `visuals/` verschoben und nach `COMP_ID_16x9_Titel.ext` bzw.
  `COMP_ID_9x16_Titel.ext` umbenannt.
- ffprobe-Laufzeiten und 07:59/479.4s-Defekt-Gate.
- SHA256-basierte echte Duplikat-Erkennung.
- Uebergaenge: `No`, `Micro` und `Smooth` mit Sekundenregler. `Smooth`
  rendert echte ffmpeg-`acrossfade`-Ueberlappungen; Default ist `1.5s`.
- Track-Reihenfolge kann nach dem Dry-Run per Drag & Drop geaendert werden;
  genau diese Reihenfolge wird fuer Stems, Master-WAV, Tracklist und Shorts
  verwendet.
- `Render starten` bleibt gesperrt, bis ein Dry-Run ohne Blocker bestanden ist.
- Nach dem Master-WAV-Build blockiert ein harter Silence-Gate interne Stille
  ab `0.75s`; Treffer werden in `MASTER_SILENCE_GAPS.tsv` dokumentiert und
  stoppen MP4/Shorts-Rendering.
- Render-Job fuer Master-WAV, 16:9-Longform-MP4 und 5 Shorts.
- Repair-Modus fuer fertige `COMP-ID_Titel`-Ordner: Master-WAV und 16:9-Bild
  werden erkannt, die Longform-MP4 kann einzeln neu gerendert werden. Eine
  vorhandene MP4 wird standardmaessig nach `backups/longform/` verschoben.
- Reports: `DRY_RUN.json`, `TRACKLIST.tsv`, `DRONE_ARTIFACT_REPORT.tsv`,
  `TRACK_ORDER.tsv`, `MASTER_SILENCE_GAPS.tsv`, `AUDIO_VALIDATION.txt`,
  `VIDEO_VALIDATION.tsv`, `SHORTS_PLAN.tsv`, `SHORTS_VALIDATION.tsv`,
  `RENDER_SUMMARY.json`, `YOUTUBE_METADATA.md`.

## V0-Sicherheitsgrenze

Diese Version schreibt keinen Tracker und fuehrt keine YouTube-Upload-Automation
aus. Nach erfolgreichem Render und Validierung kann sie Roh-WAVs, JSON-Sidecars
und Bilder in den finalen `COMP-ID_Titel`-Ordner verschieben. Das ist in der UI
ueber `Move originals` steuerbar.
