import io
import math
import re
import threading
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import streamlit as st


APP_NAME = "Carburante vicino a te"
REPO_URL = "https://github.com/maurizio5711/carburante-cap"

MIMIT_PLANTS_URL = (
    "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
)
MIMIT_PRICES_URL = (
    "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"
)

LOCAL_PLANTS = Path("anagrafica_impianti_attivi.csv")
LOCAL_PRICES = Path("prezzo_alle_8.csv")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

st.set_page_config(
    page_title=APP_NAME,
    page_icon="⛽",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {max-width: 1180px; padding-top: 2rem;}
    .hero {
        background: linear-gradient(135deg, #08263a 0%, #0d3a54 100%);
        color: white;
        padding: 28px 30px;
        border-radius: 18px;
        margin-bottom: 20px;
    }
    .hero h1 {margin: 0 0 6px 0; font-size: 2.15rem;}
    .hero p {margin: 0; font-size: 1.05rem; opacity: .94;}
    div.stButton > button {
        width: 100%;
        min-height: 3.2rem;
        font-weight: 800;
        font-size: 1.03rem;
        border-radius: 12px;
    }
    .small-note {
        font-size: .88rem;
        color: #5b6570;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
      <h1>⛽ Carburante vicino a te</h1>
      <p>Inserisci un indirizzo e confronta i distributori più convenienti nelle vicinanze.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


def _normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _find_col(df: pd.DataFrame, candidates):
    normalized = {_normalize_name(c): c for c in df.columns}
    for candidate in candidates:
        key = _normalize_name(candidate)
        if key in normalized:
            return normalized[key]
    return None


def _extract_table_text(raw: str) -> str:
    """
    I CSV MIMIT possono contenere una riga iniziale informativa.
    Cerca la vera intestazione partendo dalla riga che contiene idImpianto.
    """
    lines = raw.replace("\ufeff", "").splitlines()
    start = 0
    for i, line in enumerate(lines):
        if "idImpianto" in line or "idimpianto" in line.lower():
            start = i
            break
    return "\n".join(lines[start:])


def _detect_sep(header: str) -> str:
    pipe = header.count("|")
    semi = header.count(";")
    comma = header.count(",")
    if pipe >= semi and pipe >= comma and pipe > 0:
        return "|"
    if semi >= comma and semi > 0:
        return ";"
    return ","


def _parse_mimit_csv(raw: str) -> pd.DataFrame:
    table_text = _extract_table_text(raw)
    first_line = table_text.splitlines()[0] if table_text else ""
    sep = _detect_sep(first_line)
    return pd.read_csv(
        io.StringIO(table_text),
        sep=sep,
        dtype=str,
        engine="python",
        on_bad_lines="skip",
    )


def _request_headers():
    return {
        "User-Agent": f"CarburanteIndirizzo/1.0 ({REPO_URL})",
        "Accept": "text/csv,text/plain,*/*",
    }


def _download_text(url: str) -> str:
    response = requests.get(url, headers=_request_headers(), timeout=25)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def _load_remote_or_local(url: str, local_path: Path) -> pd.DataFrame:
    try:
        return _parse_mimit_csv(_download_text(url))
    except Exception:
        if local_path.exists():
            raw = local_path.read_text(encoding="utf-8", errors="replace")
            return _parse_mimit_csv(raw)
        raise


@st.cache_data(ttl=3600, show_spinner=False)
def load_mimit_data():
    plants = _load_remote_or_local(MIMIT_PLANTS_URL, LOCAL_PLANTS)
    prices = _load_remote_or_local(MIMIT_PRICES_URL, LOCAL_PRICES)
    return plants, prices


@st.cache_resource
def _nominatim_rate_state():
    return {"lock": threading.Lock(), "last_request": 0.0}


def _respect_nominatim_rate_limit():
    """Mantiene almeno un secondo tra le richieste al server pubblico Nominatim."""
    state = _nominatim_rate_state()
    with state["lock"]:
        elapsed = time.monotonic() - state["last_request"]
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        state["last_request"] = time.monotonic()


def _split_street_city(address: str):
    """
    Prova a separare via/civico e comune dall'input dell'utente.

    Gestisce sia:
      - "Via Nomentana 150, Roma"
      - "Via Nomentana 150 Roma"
      - "Via Nomentana 150, Roma, RM"

    Quando non ci sono virgole, usa il numero civico come punto di separazione.
    """
    raw = re.sub(r"\s+", " ", address.strip())
    parts = [p.strip() for p in raw.split(",") if p.strip()]

    if len(parts) >= 2:
        # Se l'ultima parte sembra una sigla provincia (RM, MI, TO...), usa la penultima come comune.
        if len(parts) >= 3 and re.fullmatch(r"[A-Za-z]{2}", parts[-1]):
            city = parts[-2]
            street = ", ".join(parts[:-2])
        else:
            city = parts[-1]
            street = ", ".join(parts[:-1])
        return street.strip(), city.strip()

    # Caso senza virgole: separa dopo il civico.
    # Esempi gestiti: 150, 150A, 150/A, 150-bis.
    match = re.match(
        r"^(.*?\b\d+[A-Za-z]?(?:/[A-Za-z0-9]+)?(?:-bis)?)\s+(.+)$",
        raw,
        flags=re.IGNORECASE,
    )
    if match:
        street = match.group(1).strip()
        city = match.group(2).strip()

        # Se l'utente termina con una sigla provincia, rimuovila dal comune.
        city_parts = city.split()
        if len(city_parts) >= 2 and re.fullmatch(r"[A-Za-z]{2}", city_parts[-1]):
            city = " ".join(city_parts[:-1]).strip()

        return street, city

    return raw, None


def _city_match_score(item, city_hint: str | None) -> int:
    if not city_hint:
        return 1

    target = _normalize_name(city_hint)
    if not target:
        return 1

    address = item.get("address") or {}
    primary_fields = [
        address.get("city"),
        address.get("town"),
        address.get("village"),
        address.get("municipality"),
    ]
    other_fields = [
        address.get("city_district"),
        address.get("county"),
        address.get("state"),
    ]

    score = 0
    for value in primary_fields:
        norm = _normalize_name(value or "")
        if not norm:
            continue
        if norm == target:
            score = max(score, 120)
        elif target in norm or norm in target:
            score = max(score, 90)

    for value in other_fields:
        norm = _normalize_name(value or "")
        if target and target in norm:
            score = max(score, 55)

    display = _normalize_name(item.get("display_name", ""))
    if target and target in display:
        score = max(score, 45)

    return score


def _candidate_matches_city(item, city_hint: str | None) -> bool:
    """
    Verifica il COMUNE/località del risultato, non la provincia/contea.
    Evita quindi che "Mentana, Roma" venga accettato come se il comune fosse Roma.
    """
    if not city_hint:
        return True

    target = _normalize_name(city_hint)
    if not target:
        return True

    address = item.get("address") or {}

    # Se Nominatim restituisce una località esplicita, questa ha priorità assoluta.
    locality_values = [
        address.get("city"),
        address.get("town"),
        address.get("village"),
        address.get("hamlet"),
    ]
    locality_values = [v for v in locality_values if str(v or "").strip()]

    if locality_values:
        for value in locality_values:
            norm = _normalize_name(value)
            if norm == target:
                return True
            # Consente casi come "Roma Capitale" quando il target è "Roma".
            if norm.startswith(target) or target.startswith(norm):
                return True
        return False

    # Solo se manca del tutto city/town/village/hamlet, usa municipality.
    municipality = _normalize_name(address.get("municipality") or "")
    if municipality:
        return (
            municipality == target
            or municipality.startswith(target)
            or target.startswith(municipality)
        )

    return False


def _nominatim_search(params):
    headers = {
        "User-Agent": f"CarburanteIndirizzo/1.1 ({REPO_URL})",
        "Accept-Language": "it",
    }
    _respect_nominatim_rate_limit()
    response = requests.get(
        NOMINATIM_URL,
        params=params,
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=86400, show_spinner=False)
def geocode_address_v3(address: str):
    """
    Geocodifica un indirizzo italiano tramite OpenStreetMap/Nominatim.
    Prima usa una ricerca strutturata (via + comune) per ridurre gli omonimi;
    se non basta, prova la ricerca libera. Non usa autocomplete.
    """
    raw = address.strip()
    street, city_hint = _split_street_city(raw)

    candidates = []

    # Ricerca strutturata: è molto più affidabile quando l'utente indica il comune.
    if city_hint and street:
        params = {
            "street": street,
            "city": city_hint,
            "country": "Italia",
            "format": "jsonv2",
            "limit": 5,
            "countrycodes": "it",
            "addressdetails": 1,
            "dedupe": 1,
        }
        candidates = _nominatim_search(params)

    # Fallback su ricerca libera se la strutturata non restituisce nulla.
    if not candidates:
        query = raw
        if "italia" not in query.lower() and "italy" not in query.lower():
            query = f"{query}, Italia"
        params = {
            "q": query,
            "format": "jsonv2",
            "limit": 5,
            "countrycodes": "it",
            "addressdetails": 1,
            "dedupe": 1,
        }
        candidates = _nominatim_search(params)

    if not candidates:
        return None

    # Se l'utente ha specificato un comune, elimina prima i risultati
    # appartenenti a un altro comune. La provincia "Roma" non basta.
    if city_hint:
        matching_candidates = [
            item for item in candidates
            if _candidate_matches_city(item, city_hint)
        ]
        if matching_candidates:
            candidates = matching_candidates
        else:
            item = candidates[0]
            return {
                "ambiguous": True,
                "display_name": item.get("display_name", raw),
                "city_hint": city_hint,
            }

    ranked = sorted(
        candidates,
        key=lambda item: _city_match_score(item, city_hint),
        reverse=True,
    )
    item = ranked[0]

    return {
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
        "display_name": item.get("display_name", raw),
        "ambiguous": False,
    }


def _to_float(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(",", ".", regex=False)
        .str.replace(" ", "", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _is_self_value(series: pd.Series) -> pd.Series:
    values = (
        series.astype(str)
        .str.strip()
        .str.lower()
        .str.replace("ì", "i", regex=False)
    )
    return values.isin({"1", "true", "si", "yes", "self", "selfservice"})


def _prepare_data(plants: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    p_id = _find_col(plants, ["idImpianto"])
    p_lat = _find_col(plants, ["Latitudine", "lat"])
    p_lon = _find_col(plants, ["Longitudine", "lon", "lng"])
    p_gestore = _find_col(plants, ["Gestore"])
    p_brand = _find_col(plants, ["Bandiera", "Marca"])
    p_nome = _find_col(plants, ["Nome Impianto", "NomeImpianto"])
    p_addr = _find_col(plants, ["Indirizzo"])
    p_comune = _find_col(plants, ["Comune"])
    p_prov = _find_col(plants, ["Provincia"])

    r_id = _find_col(prices, ["idImpianto"])
    r_fuel = _find_col(prices, ["descCarburante", "Carburante"])
    r_price = _find_col(prices, ["prezzo", "Prezzo"])
    r_self = _find_col(prices, ["isSelf", "Self"])
    r_date = _find_col(prices, ["dtComu", "Data", "DataComunicazione"])

    required = {
        "id impianto anagrafica": p_id,
        "latitudine": p_lat,
        "longitudine": p_lon,
        "id impianto prezzi": r_id,
        "carburante": r_fuel,
        "prezzo": r_price,
    }
    missing = [name for name, col in required.items() if col is None]
    if missing:
        raise ValueError(
            "Colonne MIMIT non riconosciute: " + ", ".join(missing)
        )

    plants_out = pd.DataFrame(
        {
            "idImpianto": plants[p_id].astype(str).str.strip(),
            "lat": _to_float(plants[p_lat]),
            "lon": _to_float(plants[p_lon]),
            "Gestore": plants[p_gestore] if p_gestore else "",
            "Bandiera": plants[p_brand] if p_brand else "",
            "Nome impianto": plants[p_nome] if p_nome else "",
            "Indirizzo": plants[p_addr] if p_addr else "",
            "Comune": plants[p_comune] if p_comune else "",
            "Provincia": plants[p_prov] if p_prov else "",
        }
    )

    prices_out = pd.DataFrame(
        {
            "idImpianto": prices[r_id].astype(str).str.strip(),
            "Carburante": prices[r_fuel].astype(str).str.strip(),
            "Prezzo": _to_float(prices[r_price]),
            "Self": prices[r_self] if r_self else "",
            "Ultima comunicazione": prices[r_date] if r_date else "",
        }
    )

    merged = prices_out.merge(plants_out, on="idImpianto", how="inner")
    merged = merged.dropna(subset=["lat", "lon", "Prezzo"])
    merged = merged[
        merged["lat"].between(35.0, 48.5)
        & merged["lon"].between(5.0, 19.5)
        & merged["Prezzo"].between(0.2, 5.0)
    ]
    return merged


def _haversine_km(lat0, lon0, lat_series, lon_series):
    earth_radius = 6371.0088
    lat1 = np.radians(float(lat0))
    lon1 = np.radians(float(lon0))
    lat2 = np.radians(lat_series.astype(float))
    lon2 = np.radians(lon_series.astype(float))

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    )
    return 2.0 * earth_radius * np.arcsin(np.sqrt(a))


def _filter_fuel(df: pd.DataFrame, fuel: str) -> pd.DataFrame:
    values = df["Carburante"].astype(str).str.strip().str.lower()

    aliases = {
        "Benzina": ["benzina"],
        "Gasolio": ["gasolio", "diesel"],
        "GPL": ["gpl"],
        "Metano": ["metano", "gnc", "cng"],
    }

    terms = aliases.get(fuel, [fuel.lower()])
    mask = pd.Series(False, index=df.index)
    for term in terms:
        mask = mask | values.str.contains(term, na=False, regex=False)

    return df[mask].copy()


def build_results(
    data: pd.DataFrame,
    lat: float,
    lon: float,
    fuel: str,
    mode: str,
    radius_km: float,
):
    work = _filter_fuel(data, fuel)

    if mode != "Qualsiasi":
        is_self = _is_self_value(work["Self"])
        if mode == "Self service":
            work = work[is_self]
        else:
            work = work[~is_self]

    work = work.copy()
    work["Distanza km"] = _haversine_km(
        lat,
        lon,
        work["lat"],
        work["lon"],
    )

    work = work[work["Distanza km"] <= float(radius_km)]
    work = work.sort_values(["Prezzo", "Distanza km"], ascending=[True, True])

    # Una sola riga per impianto/prezzo/modalità quando il dataset contiene duplicati.
    work = work.drop_duplicates(
        subset=["idImpianto", "Carburante", "Prezzo", "Self"],
        keep="first",
    )

    return work


with st.form("search_form"):
    st.subheader("Dove vuoi fare rifornimento?")

    address = st.text_input(
        "Inserisci indirizzo",
        placeholder="Esempio: Via Nomentana 150 Roma",
        help="Per una ricerca più precisa inserisci via/piazza, numero civico, comune e, se serve, provincia.",
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        fuel = st.selectbox(
            "Carburante",
            ["Benzina", "Gasolio", "GPL", "Metano"],
            index=0,
        )
    with c2:
        mode = st.selectbox(
            "Modalità",
            ["Qualsiasi", "Self service", "Servito"],
            index=0,
        )
    with c3:
        radius = st.slider(
            "Raggio di ricerca",
            min_value=2,
            max_value=30,
            value=10,
            step=1,
            format="%d km",
        )

    submitted = st.form_submit_button(
        "🔎 TROVA I DISTRIBUTORI PIÙ CONVENIENTI",
        use_container_width=True,
    )


if submitted:
    if not address.strip():
        st.error("Inserisci un indirizzo prima di avviare la ricerca.")
    else:
        with st.spinner("Localizzo l'indirizzo e confronto i distributori..."):
            try:
                location = geocode_address_v3(address)

                if not location:
                    st.session_state.pop("fuel_results", None)
                    st.error(
                        "Non riesco a localizzare l'indirizzo. "
                        "Prova ad aggiungere numero civico, comune e provincia."
                    )
                elif location.get("ambiguous"):
                    st.session_state.pop("fuel_results", None)
                    st.error(
                        "L'indirizzo è ambiguo: il risultato trovato non sembra appartenere "
                        f"al comune **{location.get('city_hint', '')}**. "
                        "Aggiungi la provincia, per esempio: `Via Nomentana 150, Roma, RM`."
                    )
                    st.caption(
                        "Risultato scartato: " + location.get("display_name", "")
                    )
                else:
                    plants, prices = load_mimit_data()
                    prepared = _prepare_data(plants, prices)
                    results = build_results(
                        prepared,
                        location["lat"],
                        location["lon"],
                        fuel,
                        mode,
                        radius,
                    )

                    st.session_state["fuel_results"] = results
                    st.session_state["fuel_location"] = location
                    st.session_state["fuel_query"] = {
                        "address": address,
                        "fuel": fuel,
                        "mode": mode,
                        "radius": radius,
                    }

            except requests.RequestException:
                st.session_state.pop("fuel_results", None)
                st.error(
                    "Il servizio esterno non è raggiungibile in questo momento. "
                    "Riprova tra poco."
                )
            except Exception as exc:
                st.session_state.pop("fuel_results", None)
                st.error(
                    "Non è stato possibile completare la ricerca. "
                    "Controlla i dati e riprova."
                )
                with st.expander("Dettaglio tecnico"):
                    st.code(str(exc))


results = st.session_state.get("fuel_results")
location = st.session_state.get("fuel_location")
query = st.session_state.get("fuel_query")

if results is not None and location and query:
    st.divider()
    st.success(f"Indirizzo individuato: **{location['display_name']}**")

    if results.empty:
        st.warning(
            f"Nessun risultato per {query['fuel']} entro "
            f"{query['radius']} km con i filtri scelti."
        )
    else:
        best = results.iloc[0]

        m1, m2, m3 = st.columns(3)
        m1.metric("Prezzo più basso", f"{best['Prezzo']:.3f} €/l")
        m2.metric("Distanza stimata", f"{best['Distanza km']:.1f} km")
        m3.metric("Distributori trovati", f"{len(results)}")

        if str(best.get("Ultima comunicazione", "")).strip():
            st.caption(
                "Ultima comunicazione del prezzo del primo risultato: "
                f"{best['Ultima comunicazione']}"
            )

        display = results.copy()
        display["Prezzo"] = display["Prezzo"].round(3)
        display["Distanza km"] = display["Distanza km"].round(2)
        display["Modalità"] = np.where(
            _is_self_value(display["Self"]),
            "Self",
            "Servito",
        )

        display["Distributore"] = (
            display["Nome impianto"].fillna("").astype(str).str.strip()
        )
        empty_name = display["Distributore"].eq("")
        display.loc[empty_name, "Distributore"] = (
            display.loc[empty_name, "Bandiera"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

        display["Indirizzo completo"] = (
            display["Indirizzo"].fillna("").astype(str).str.strip()
            + " · "
            + display["Comune"].fillna("").astype(str).str.strip()
            + " ("
            + display["Provincia"].fillna("").astype(str).str.strip()
            + ")"
        )

        table_cols = [
            "Distributore",
            "Bandiera",
            "Carburante",
            "Modalità",
            "Prezzo",
            "Distanza km",
            "Indirizzo completo",
            "Ultima comunicazione",
        ]

        st.subheader("Classifica per prezzo")
        st.dataframe(
            display[table_cols].head(50),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Prezzo": st.column_config.NumberColumn(
                    "Prezzo €/l",
                    format="%.3f €",
                ),
                "Distanza km": st.column_config.NumberColumn(
                    "Distanza",
                    format="%.2f km",
                ),
            },
        )

        st.subheader("Mappa")
        map_df = results[["lat", "lon"]].head(100).copy()
        # Aggiungiamo anche il punto dell'indirizzo cercato.
        origin = pd.DataFrame(
            [{"lat": location["lat"], "lon": location["lon"]}]
        )
        st.map(pd.concat([origin, map_df], ignore_index=True))

        csv_export = display[table_cols].to_csv(
            index=False,
            sep=";",
        ).encode("utf-8-sig")

        st.download_button(
            "⬇️ Scarica i risultati in CSV",
            data=csv_export,
            file_name="distributori_vicino_indirizzo.csv",
            mime="text/csv",
            use_container_width=True,
        )

st.divider()

st.info(
    "La distanza mostrata è una stima in linea d'aria, non il percorso stradale. "
    "I prezzi dipendono dall'ultimo aggiornamento disponibile nei dati MIMIT: "
    "verifica sempre il prezzo esposto alla pompa prima del rifornimento."
)

st.markdown(
    """
    **Fonti del servizio**

    - Prezzi e anagrafica distributori: **MIMIT – Ministero delle Imprese e del Made in Italy**
    - Localizzazione dell'indirizzo: **© OpenStreetMap contributors / Nominatim**
    """
)

st.caption(
    "Privacy: il codice dell'app non salva l'indirizzo in un database. "
    "L'indirizzo inserito viene inviato al servizio di geocodifica per trasformarlo "
    "in coordinate geografiche. L’uso del servizio OpenStreetMap/Nominatim è soggetto "
    "alla relativa policy di utilizzo e privacy."
)
