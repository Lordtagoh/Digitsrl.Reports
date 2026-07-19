# Digitsrl.Reports

Report giornaliero delle vendite, pubblicato su GitHub Pages come pagina
statica con dati **cifrati lato client** (AES-256-GCM + PBKDF2-SHA-256,
600.000 iterazioni). Il JSON in chiaro non viene mai committato.

## Come funziona

- `generate_report.py` legge le vendite del giorno da PagoDealer.db
  (sola lettura), calcola colori e icone come il gestionale
  (`SalesColorAndImageExtensions.cs` di ContractsPrinting.Report) e scrive
  `docs/data/report.enc.json` cifrato.
- `docs/` è il sito GitHub Pages: schermata di sblocco, decifratura in
  browser via WebCrypto, rendering mobile-first (pensato per iPhone).
- La password viene ricordata sul dispositivo (`localStorage`,
  chiave `daily-report-password`); il pulsante «Dimentica questo
  dispositivo» la rimuove.

## Uso quotidiano

```bash
publish.bat        # genera e, SOLO se i dati sono cambiati, committa e pusha
```

Oppure a mano:

```bash
python generate_report.py            # report di oggi (o ultimo giorno con vendite)
git add docs/data/report.enc.json
git commit -m "Daily report"
git push
```

Se le vendite non sono cambiate dall'ultima pubblicazione, il generatore
NON riscrive `report.enc.json` (confronta il contenuto decifrato, ignorando
solo `generatedAt`): `git status` resta pulito e non c'è nulla da pushare.
Con `--force` il file viene riscritto comunque.

## Password

La password NON è nel repository. Il generatore la legge, in ordine, da:

1. `--password <pw>`
2. variabile d'ambiente `REPORT_PASSWORD`
3. file `password.local.txt` (gitignored)

Per ruotarla: cambia la password locale e rigenera il report; i dispositivi
fidati falliranno la decifratura e richiederanno la nuova password una volta.

## Test locale

```bash
cd docs
python -m http.server 8000
# apri http://localhost:8000 (WebCrypto richiede https o localhost)
```

## Requisiti

```bash
pip install -r requirements.txt   # cryptography
```
