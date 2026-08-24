from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import StringIO
import math
import re
from typing import Tuple, Dict

import pandas as pd
import requests
import streamlit as st

ANAGRAFICA_URL = "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
PREZZI_URL = "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"

UA = "CarburanteCAP/1.0 (consumer price comparison; source MIMIT open data)"


def _download_text(url: str) -> str:
    r = requests.get(url, timeout=35, headers={"User-Agent": UA})
    r.raise_for_status()
    return r.content.decode("utf-8", errors="replace")


def _extract_date(first_line: str) -> str | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", first_line)
    return m.group(1) if m else None


def parse_anagrafica(text: str) -> tuple[pd.DataFrame, str | None]:
    """
    Parser robusto per l'anagrafica MIMIT.
    Dal 10/02/2026 il separatore è '|'. Alcune descrizioni possono comunque
    contenere caratteri anomali: se una riga ha campi in eccesso, preserviamo
    i primi 5 e gli ultimi 4, ricomponendo la parte centrale come Indirizzo.
    """
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
            # 5 campi iniziali + indirizzo ricomposto + 4 campi finali
            parts = parts[:5] + [" | ".join(parts[5:-4])] + parts[-4:]
        rows.append(parts[:10])

    df = pd.DataFrame(rows, columns=columns)
    df["idImpianto"] = df["idImpianto"].astype(str).str.strip()
    df["Latitudine"] = pd.to_numeric(df["Latitudine"], errors="coerce")
    df["Longitudine"] = pd.to_numeric(df["Longitudine"], errors="coerce")

    # CAP ricavato dall'indirizzo ufficiale MIMIT.
    df["CAP"] = (
        df["Indirizzo"]
        .astype(str)
        .str.extract(r"(?<!\d)(\d{5})(?!\d)", expand=False)
    )
    return df, extraction_date


def parse_prezzi(text: str) -> tuple[pd.DataFrame, str | None]:
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
    anagrafica_text = _download_text(ANAGRAFICA_URL)
    prezzi_text = _download_text(PREZZI_URL)

    impianti, anag_date = parse_anagrafica(anagrafica_text)
    prezzi, price_date = parse_prezzi(prezzi_text)

    meta = {
        "anagrafica_date": anag_date,
        "prezzi_date": price_date,
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
    a = (dlat / 2).map(math.sin) ** 2 + math.cos(lat1r) * lat2r.map(math.cos) * (dlon / 2).map(math.sin) ** 2
    return 2 * r * a.map(lambda x: math.asin(min(1.0, math.sqrt(max(0.0, x)))))


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
            "Per una versione commerciale conviene aggiungere un database CAP→coordinate."
        )

    # Mediana più robusta di una media in presenza di coordinate anomale.
    center_lat = float(cap_points["Latitudine"].median())
    center_lon = float(cap_points["Longitudine"].median())

    p = prezzi[
        prezzi["descCarburante"].str.casefold() == carburante.casefold()
    ].copy()

    service = _service_value(servizio)
    if service is not None:
        p = p[p["isSelf"] == service]

    p = p[p["prezzo"].notna() & (p["prezzo"] > 0)]

    # In caso di duplicati per impianto/modalità, teniamo il prezzo minimo disponibile.
    p = (
        p.sort_values(["idImpianto", "prezzo"])
         .drop_duplicates(subset=["idImpianto"], keep="first")
    )

    merged = impianti.merge(p, on="idImpianto", how="inner")
    merged = merged[
        merged["Latitudine"].notna() & merged["Longitudine"].notna()
    ].copy()

    merged["distanza_km"] = haversine_km(
        center_lat,
        center_lon,
        merged["Latitudine"],
        merged["Longitudine"],
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
    return f"Dataset MIMIT: prezzi estratti il {p}; anagrafica estratta il {a}."
