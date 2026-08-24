# Carburante CAP – prototipo web app

Web app Streamlit per trovare le stazioni di carburante più economiche in una zona italiana partendo dal CAP.

## Funzioni

- Inserimento CAP italiano
- Benzina, Gasolio, GPL e Metano
- Self service, servito o qualsiasi modalità
- Raggio da 2 a 30 km
- Classifica per prezzo crescente
- Distanza stimata dal centro del CAP
- Mappa degli impianti
- Data/ora dell'ultima comunicazione del prezzo
- Esportazione CSV
- Cache dei dataset per ridurre i download
- Pulsante **Aggiorna dati ora** per svuotare la cache e forzare un nuovo download MIMIT

## Fonte dati

Ministero delle Imprese e del Made in Italy (MIMIT):

- Anagrafica impianti:
  https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv
- Prezzi:
  https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv

I dati sono open data MIMIT con licenza IODL 2.0.
Dal 10 febbraio 2026 il separatore dei file è `|`.

### Nota sulla freschezza

La versione open data è pubblicata quotidianamente e contiene i prezzi in vigore alle ore 8 del giorno precedente alla pubblicazione.
Per un servizio realmente "live" è preferibile usare un'API ufficiale MIMIT, se resa disponibile, o un feed autorizzato.
Non è consigliabile basare un prodotto commerciale sullo scraping non documentato del sito pubblico.

## Come avviare in locale

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

Apri quindi l'indirizzo mostrato da Streamlit, normalmente `http://localhost:8501`.

## Pubblicazione

La stessa app può essere pubblicata su:

- Streamlit Community Cloud
- Render
- Railway
- un VPS
- Docker / cloud provider

Per un prodotto finale è consigliabile:
1. aggiungere un database completo CAP → coordinate/comuni;
2. salvare i dataset MIMIT in un database aggiornato automaticamente;
3. aggiungere cronologia prezzi;
4. notifiche "prezzo sotto soglia";
5. calcolo del risparmio reale considerando distanza e consumo dell'auto;
6. PWA/app mobile oppure frontend React/Flutter con backend API.

## Disclaimer

Le coordinate degli impianti sono comunicate dai gestori e, secondo i metadati MIMIT, sono inserite su base volontaria e non sempre verificate.
Verificare il prezzo alla pompa prima del rifornimento.


## Pulsante Aggiorna

Il pulsante **🔄 Aggiorna dati ora**:
1. svuota la cache Streamlit;
2. forza un nuovo download dell'anagrafica e dei prezzi MIMIT;
3. mantiene invariati i filtri dell'app;
4. fa sì che la ricerca successiva utilizzi i file più recenti disponibili sul server MIMIT.

Importante: il pulsante può scaricare soltanto la versione più recente **già pubblicata dal MIMIT**. Non può rendere i dati più freschi del file ufficiale disponibile in quel momento.


## Interfaccia V3

La ricerca principale è stata semplificata:
- **CAP grande al centro della schermata**
- grande pulsante verde **“TROVA IL CARBURANTE PIÙ ECONOMICO”**
- filtri secondari nella barra laterale
- pulsante **“Aggiorna dati ora”** separato dai comandi di ricerca

Questo rende immediatamente evidente dove inserire il CAP.
