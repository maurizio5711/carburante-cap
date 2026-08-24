from __future__ import annotations

from pathlib import Path
import math
import re
import time
from typing import Dict

import pandas as pd
import requests
import streamlit as st

ANAGRAFICA_URL = "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
PREZZI_URL = "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"

LOCAL_ANAGRAFICA = Path(__file__).resolve().parent / "anagrafica_impianti_attivi.csv"
LOCAL_PREZZI = Path(__file__).resolve().parent / "prezzo_alle_8.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
    "Referer": (
        "https://www.mimit.gov.it/it/open-data/elenco-dataset/"
        "carburanti-prezzi-praticati-e-anagrafica-degli-impianti"
    ),
    "Cache-Control": "no-cache",
}


def _looks_like_mimit_csv(text: str, kind: str) -> bool:
    if not text or len(text) < 200:
        return False
    head = text[:1200]
    if "Estrazione del " not in head:
        return False
    if kind == "anagrafica":
        return "idImpianto|Gestore|Bandiera|" in head
    return "idImpianto|descCarburante|prezzo|isSelf|dtComu" in head


def _download_text(url: str, kind: str) -> str:
    """
    Prova più volte il download MIMIT con header da browser.
    Se Streamlit Cloud/MIMIT rifiutano la richiesta, solleva un errore
    e il chiamante userà lo snapshot locale ufficiale.
    """
    last_error = None
    for attempt in range(3):
        try:
            r = requests.get(
                url,
                timeout=40,
                headers=HEADERS,
                allow_redirects=True,
            )
            r.raise_for_status()
            text = r.content.decode("utf-8-sig", errors="replace")
            if _looks_like_mimit_csv(text, kind):
                return text
            preview = text[:120].replace("\n", " ")
            last_error = RuntimeError(
                f"Risposta MIMIT non riconosciuta ({len(text)} caratteri): {preview!r}"
            )
        except Exception as exc:
            last_error = exc
        time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(str(last_error) if last_error else "Download MIMIT non riuscito.")


def _read_local_snapshot(path: Path, kind: str) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Snapshot locale mancante: {path.name}")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if not _looks_like_mimit_csv(text, kind):
        raise ValueError(f"Snapshot locale {path.name} non valido.")
    return text


def _extract_date(first_line: str) -> str | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", first_line)
    return m.group(1) if m else None


def parse_anagrafica(text: str):
    lines = text.splitlines()
    if len(lines) < 3:
        raise ValueError("File anagrafica MIMIT vuoto o non valido.")

    extraction_date = _extract_date(lines[0])
    columns = lines[1].split("|")
    expected = [
        "idImpianto", "Gestore", "Bandiera", "Tipo Impianto", "Nome Impianto",
        "Indirizzo", "Comune", "Provincia", "Latitudine", "Longitudine"
    ]
    if len(columns) != 10:
        columns = expected

    rows = []
    for line in lines[2:]:
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 10:
            continue
        if len(parts) > 10:
            parts = parts[:5] + [" | ".join(parts[5:-4])] + parts[-4:]
        rows.append(parts[:10])

    df = pd.DataFrame(rows, columns=columns)
    df["idImpianto"] = df["idImpianto"].astype(str).str.strip()
    df["Latitudine"] = pd.to_numeric(df["Latitudine"], errors="coerce")
    df["Longitudine"] = pd.to_numeric(df["Longitudine"], errors="coerce")
    df["CAP"] = (
        df["Indirizzo"]
        .astype(str)
        .str.extract(r"(?<!\d)(\d{5})(?!\d)", expand=False)
    )
    return df, extraction_date


def parse_prezzi(text: str):
    lines = text.splitlines()
    if len(lines) < 3:
        raise ValueError("File prezzi MIMIT vuoto o non valido.")

    extraction_date = _extract_date(lines[0])
    columns = lines[1].split("|")
    rows = []
    for line in lines[2:]:
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        rows.append(parts[:5])

    df = pd.DataFrame(rows, columns=columns[:5])
    df["idImpianto"] = df["idImpianto"].astype(str).str.strip()
    df["prezzo"] = pd.to_numeric(df["prezzo"], errors="coerce")
    df["isSelf"] = pd.to_numeric(df["isSelf"], errors="coerce").astype("Int64")
    df["descCarburante"] = df["descCarburante"].astype(str).str.strip()
    return df, extraction_date


@st.cache_data(ttl=3600, show_spinner=False)
def load_mimit_data():
    source = "MIMIT diretto"
    direct_error = None

    try:
        anagrafica_text = _download_text(ANAGRAFICA_URL, "anagrafica")
        prezzi_text = _download_text(PREZZI_URL, "prezzi")
    except Exception as exc:
        direct_error = str(exc)
        source = "snapshot MIMIT di sicurezza"
        anagrafica_text = _read_local_snapshot(LOCAL_ANAGRAFICA, "anagrafica")
        prezzi_text = _read_local_snapshot(LOCAL_PREZZI, "prezzi")

    impianti, anag_date = parse_anagrafica(anagrafica_text)
    prezzi, price_date = parse_prezzi(prezzi_text)

    meta = {
        "anagrafica_date": anag_date,
        "prezzi_date": price_date,
        "source": source,
        "direct_error": direct_error,
        "anagrafica_url": ANAGRAFICA_URL,
        "prezzi_url": PREZZI_URL,
    }
    return impianti, prezzi, meta


def haversine_km(lat1, lon1, lat2_series, lon2_series):
    r = 6371.0088
    lat1r = math.radians(float(lat1))
    lon1r = math.radians(float(lon1))
    lat2r = lat2_series.map(math.radians)
    lon2r = lon2_series.map(math.radians)
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = (
        (dlat / 2).map(math.sin) ** 2
        + math.cos(lat1r)
        * lat2r.map(math.cos)
        * (dlon / 2).map(math.sin) ** 2
    )
    return 2 * r * a.map(
        lambda x: math.asin(min(1.0, math.sqrt(max(0.0, x))))
    )


def _service_value(servizio: str):
    if servizio == "Self service":
        return 1
    if servizio == "Servito":
        return 0
    return None


def find_cheapest_stations(
    impianti: pd.DataFrame,
    prezzi: pd.DataFrame,
    cap: str,
    carburante: str,
    servizio: str = "Self service",
    radius_km: float = 10.0,
    limit: int = 10,
):
    cap = str(cap).strip()

    cap_points = impianti[
        (impianti["CAP"] == cap)
        & impianti["Latitudine"].notna()
        & impianti["Longitudine"].notna()
    ].copy()

    if cap_points.empty:
        raise ValueError(
            f"Il CAP {cap} non compare nelle anagrafiche degli impianti MIMIT. "
            "Prova un CAP vicino oppure aumenta il raggio dopo aver scelto un CAP presente."
        )

    center_lat = float(cap_points["Latitudine"].median())
    center_lon = float(cap_points["Longitudine"].median())

    p = prezzi[
        prezzi["descCarburante"].str.casefold() == carburante.casefold()
    ].copy()

    service = _service_value(servizio)
    if service is not None:
        p = p[p["isSelf"] == service]

    p = p[p["prezzo"].notna() & (p["prezzo"] > 0)]
    p = (
        p.sort_values(["idImpianto", "prezzo"])
        .drop_duplicates(subset=["idImpianto"], keep="first")
    )

    merged = impianti.merge(p, on="idImpianto", how="inner")
    merged = merged[
        merged["Latitudine"].notna() & merged["Longitudine"].notna()
    ].copy()

    merged["distanza_km"] = haversine_km(
        center_lat, center_lon, merged["Latitudine"], merged["Longitudine"]
    )

    nearby = merged[merged["distanza_km"] <= float(radius_km)].copy()
    nearby = nearby.sort_values(
        by=["prezzo", "distanza_km", "Bandiera"],
        ascending=[True, True, True],
    ).head(int(limit))

    info = {
        "center_lat": center_lat,
        "center_lon": center_lon,
        "cap_station_count": int(len(cap_points)),
    }
    return nearby.reset_index(drop=True), info


def extraction_summary(meta: Dict) -> str:
    p = meta.get("prezzi_date") or "data non disponibile"
    a = meta.get("anagrafica_date") or "data non disponibile"
    source = meta.get("source", "MIMIT")
    if source == "MIMIT diretto":
        return (
            f"Dati caricati direttamente dal MIMIT — prezzi: {p}; "
            f"anagrafica: {a}."
        )
    return (
        f"MIMIT diretto temporaneamente non raggiungibile da Streamlit: "
        f"uso snapshot ufficiale di sicurezza — prezzi: {p}; anagrafica: {a}."
    )
