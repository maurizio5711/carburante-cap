# Carburante vicino a te – ricerca per indirizzo (v1.1)

Web app Streamlit per trovare i distributori di carburante più convenienti vicino a un **indirizzo italiano**.

## Funzioni

- Inserimento di un indirizzo: via/piazza, numero civico e comune
- Geocodifica dell'indirizzo tramite OpenStreetMap / Nominatim
- Benzina, Gasolio, GPL e Metano
- Self service, servito o qualsiasi modalità
- Raggio da 2 a 30 km
- Classifica per prezzo crescente
- Distanza stimata in linea d'aria dall'indirizzo inserito
- Mappa degli impianti
- Data/ora dell'ultima comunicazione del prezzo quando disponibile
- Esportazione CSV dei risultati
- Cache dei dataset per ridurre le richieste ai servizi esterni

## Fonte prezzi e impianti

Ministero delle Imprese e del Made in Italy (MIMIT):

- `https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv`
- `https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv`

L'app tenta di usare i file online MIMIT. Se il download non è disponibile, può usare come fallback i file locali presenti nel repository:

- `anagrafica_impianti_attivi.csv`
- `prezzo_alle_8.csv`

## Geocodifica

La trasformazione indirizzo → coordinate è effettuata tramite OpenStreetMap / Nominatim.

La richiesta parte soltanto quando l'utente preme il pulsante di ricerca: non viene usato un sistema di autocomplete.

La versione include cache e limitazione a circa una richiesta al secondo, in linea con la policy del server pubblico Nominatim. Il servizio pubblico è adatto a traffico leggero; per traffico significativo o uso commerciale continuativo è opportuno passare a un provider dedicato o a un'istanza propria di Nominatim.

## Installazione locale

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

## Pubblicazione su Streamlit Community Cloud

Il file principale resta:

```text
app.py
```

Dopo il commit sul branch collegato a Streamlit, l'app viene normalmente ridistribuita automaticamente.

## Nota sui dati

La distanza è calcolata in linea d'aria e non corrisponde necessariamente al tragitto stradale.

I prezzi dipendono dall'ultimo aggiornamento disponibile nella fonte MIMIT. Prima del rifornimento è sempre opportuno verificare il prezzo esposto presso l'impianto.

## Privacy

Il codice dell'app non salva l'indirizzo in un database. L'indirizzo inserito viene trasmesso al servizio di geocodifica per convertirlo in coordinate.


## Correzione v1.1

La geocodifica usa prima una ricerca strutturata via/civico + comune e scarta i risultati che non corrispondono al comune indicato, riducendo il rischio di omonimie (es. Roma/Mentana).
