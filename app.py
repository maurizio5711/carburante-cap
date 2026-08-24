import streamlit as st
import pandas as pd
from fuel_data import (
    load_mimit_data,
    find_cheapest_stations,
    extraction_summary,
)

st.set_page_config(
    page_title="Carburante conveniente vicino al CAP",
    page_icon="⛽",
    layout="wide",
)

st.markdown("""
<style>
.block-container {max-width: 1120px; padding-top: 2rem;}
div[data-testid="stMetric"] {
    background: #f4f8f5;
    border: 1px solid #dcebe3;
    padding: 12px 16px;
    border-radius: 14px;
}
.small-note {color:#5f6e67; font-size:0.9rem;}

.cap-search-box {
    background: linear-gradient(135deg, #f2f8f4 0%, #ffffff 100%);
    border: 1px solid #d8e8df;
    padding: 22px 24px 14px 24px;
    border-radius: 18px;
    margin: 18px 0 20px 0;
    box-shadow: 0 4px 18px rgba(11, 107, 79, 0.07);
}
.cap-search-title {
    font-size: 1.15rem;
    font-weight: 750;
    margin-bottom: 2px;
    color: #173a31;
}
.cap-search-subtitle {
    color: #63716b;
    margin-bottom: 8px;
}
div[data-testid="stTextInput"] input {
    font-size: 1.35rem;
    font-weight: 700;
    text-align: center;
    letter-spacing: 0.10em;
}
div[data-testid="stFormSubmitButton"] button {
    background: #0b6b4f;
    color: white;
    font-weight: 800;
    min-height: 3.1rem;
    border-radius: 12px;
    border: 0;
}
div[data-testid="stFormSubmitButton"] button:hover {
    background: #07533d;
    color: white;
}
</style>
""", unsafe_allow_html=True)

st.title("⛽ Trova il carburante più conveniente vicino al tuo CAP")
st.caption(
    "Ricerca basata sugli open data ufficiali del Ministero delle Imprese e del Made in Italy (MIMIT)."
)

with st.sidebar:
    st.header("Filtri di ricerca")
    carburante = st.selectbox(
        "Carburante",
        ["Benzina", "Gasolio", "GPL", "Metano"],
        index=1,
    )
    servizio = st.radio(
        "Modalità",
        ["Self service", "Servito", "Qualsiasi"],
        index=0,
    )
    raggio = st.slider("Raggio di ricerca", min_value=2, max_value=30, value=10, step=1)
    numero = st.slider("Numero massimo di risultati", 5, 25, 10, 5)

    st.divider()
    aggiorna = st.button("🔄 Aggiorna dati ora", use_container_width=True)
    if aggiorna:
        st.cache_data.clear()
        st.session_state["refresh_message"] = True
        st.rerun()

st.markdown(
    """
    <div class="cap-search-box">
        <div class="cap-search-title">Inserisci il CAP della zona che vuoi controllare</div>
        <div class="cap-search-subtitle">Esempio: 00144. Poi usa i filtri a sinistra per affinare la ricerca.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.form("cap_search_form", clear_on_submit=False):
    cap = st.text_input(
        "CAP italiano",
        placeholder="00144",
        max_chars=5,
        label_visibility="collapsed",
    )
    cerca = st.form_submit_button(
        "⛽ TROVA IL CARBURANTE PIÙ ECONOMICO",
        use_container_width=True,
        type="primary",
    )

if st.session_state.pop("refresh_message", False):
    st.success(
        "Dati aggiornati: ho forzato un nuovo download dei dataset MIMIT. "
        "La prossima ricerca userà i dati appena scaricati."
    )

st.info(
    "Inserisci il CAP al centro della pagina. L’app usa il CAP per stimare il centro della zona e "
    "cerca gli impianti entro il raggio scelto nella barra laterale. Se il CAP non è presente "
    "nelle anagrafiche MIMIT, l’app lo segnala."
)

if cerca:
    if not (cap.isdigit() and len(cap) == 5):
        st.error("Inserisci un CAP italiano di 5 cifre.")
        st.stop()

    with st.spinner("Scarico e confronto i dati ufficiali MIMIT..."):
        try:
            impianti, prezzi, meta = load_mimit_data()
            risultati, info = find_cheapest_stations(
                impianti=impianti,
                prezzi=prezzi,
                cap=cap,
                carburante=carburante,
                servizio=servizio,
                radius_km=float(raggio),
                limit=int(numero),
            )
        except Exception as exc:
            st.error(f"Non riesco a completare la ricerca: {exc}")
            st.stop()

    st.caption(extraction_summary(meta))

    if risultati.empty:
        st.warning(
            "Non ho trovato impianti compatibili con questi filtri. "
            "Prova ad aumentare il raggio, cambiare modalità oppure scegliere 'Qualsiasi'."
        )
        st.stop()

    c1, c2, c3, c4 = st.columns(4)
    min_price = risultati["prezzo"].min()
    avg_price = risultati["prezzo"].mean()
    saving = max(0.0, avg_price - min_price)
    with c1:
        st.metric("Prezzo più basso", f"{min_price:.3f} €")
    with c2:
        st.metric("Media risultati", f"{avg_price:.3f} €")
    with c3:
        st.metric("Risparmio vs media", f"{saving:.3f} €/unità")
    with c4:
        st.metric("Impianti trovati", str(len(risultati)))

    st.subheader(f"Le stazioni più convenienti vicino al CAP {cap}")

    display = risultati.copy()
    display["Prezzo"] = display["prezzo"].map(lambda x: f"{x:.3f} €")
    display["Distanza"] = display["distanza_km"].map(lambda x: f"{x:.1f} km")
    display["Modalità"] = display["isSelf"].map({1: "Self", 0: "Servito"}).fillna("—")
    display["Ultimo prezzo comunicato"] = display["dtComu"].fillna("—")

    cols = [
        "Bandiera", "Nome Impianto", "Indirizzo", "Comune", "Provincia",
        "Prezzo", "Modalità", "Distanza", "Ultimo prezzo comunicato"
    ]
    st.dataframe(
        display[cols],
        use_container_width=True,
        hide_index=True,
    )

    map_df = risultati.dropna(subset=["Latitudine", "Longitudine"])[
        ["Latitudine", "Longitudine"]
    ].rename(columns={"Latitudine": "lat", "Longitudine": "lon"})
    if not map_df.empty:
        st.subheader("Mappa")
        st.map(map_df, latitude="lat", longitude="lon", size=18)

    csv = risultati.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Scarica i risultati in CSV",
        data=csv,
        file_name=f"carburante_{cap}_{carburante.lower()}.csv",
        mime="text/csv",
    )

    st.markdown(
        f"""
        <div class="small-note">
        Centro CAP stimato da {info['cap_station_count']} impianti MIMIT con quel CAP.
        Raggio usato: {raggio} km. Le coordinate degli impianti sono comunicate dai gestori
        e possono contenere imprecisioni.
        </div>
        """,
        unsafe_allow_html=True,
    )

st.divider()
st.markdown(
    """
    **Fonte dati:** MIMIT – *Carburanti: prezzi praticati e anagrafica degli impianti*.
    I dataset open data sono pubblicati con frequenza quotidiana e licenza IODL 2.0.
    I prezzi visualizzati sono quelli presenti nel dataset ufficiale disponibile al momento della ricerca. Il pulsante **Aggiorna dati ora** svuota la cache dell'app e forza un nuovo download dai server MIMIT.
    """
)
