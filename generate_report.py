#!/usr/bin/env python
"""
Genera il report giornaliero delle vendite e lo pubblica cifrato in
docs/data/report.enc.json (AES-256-GCM + PBKDF2-SHA-256, 600.000 iterazioni).

Sorgente dati: PagoDealer.db (%APPDATA%\\Digit srl\\Database), aperto in SOLA
LETTURA — il database appartiene all'applicazione PagoDealer.

Colori e icone replicano la logica di
Digitsrl.ContractsPrinting.Report.WebMvc/Views/SalesColorAndImageExtensions.cs.

La password NON è nel codice: viene letta (in ordine) da --password,
dalla variabile d'ambiente REPORT_PASSWORD, o dal file password.local.txt
(gitignored). Il report.json in chiaro non viene mai scritto su disco.

Uso:
    python generate_report.py                 # report di oggi
    python generate_report.py --date 2026-07-17
    python generate_report.py --plain out.json   # debug: salva anche il JSON in chiaro
"""

import argparse
import base64
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "docs" / "data" / "report.enc.json"
PASSWORD_FILE = SCRIPT_DIR / "password.local.txt"

# avanzamenti.db del progetto dashboard (repo gemello): soglie e punti PDF
AVANZAMENTI_DB = (SCRIPT_DIR.parent /
                  "Digitsrl.Provider.Dashboard.WindTreTargetImporter" /
                  "avanzamenti.db")

PBKDF2_ITERATIONS = 600_000

# Filtri categoria allineati a common.py del progetto WindTreTargetImporter
FILTER_MOBILE = ("Provider IN ('Wind', 'Very') "
                 "AND PaymentKind IN ('postpaid', 'prepaid')")
FILTER_FISSO = "Provider = 'Infostrada'"
FILTER_SKY_NON_MOBILE = "Provider = 'Sky' AND IsMobile = 0"
FILTER_SKY_MOBILE = "Provider = 'Sky' AND IsMobile = 1"


# ── PagoDealer.db (sola lettura) ─────────────────────────────────────────────

def connect_pagodealer():
    appdata = os.getenv("APPDATA")
    if not appdata:
        sys.exit("APPDATA non definita: impossibile trovare PagoDealer.db")
    path = Path(appdata) / "Digit srl" / "Database" / "PagoDealer.db"
    if not path.exists():
        sys.exit(f"PagoDealer.db non trovato: {path}")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ── Porting di SalesColorAndImageExtensions.cs ───────────────────────────────
# Colori System.Drawing → hex

CLR = {
    "LightGray": "#D3D3D3", "Red": "#FF0000", "DarkGray": "#A9A9A9",
    "SteelBlue": "#4682B4", "LightSteelBlue": "#B0C4DE",
    "LightSkyBlue": "#87CEFA", "LightBlue": "#ADD8E6",
    "DarkSalmon": "#E9967A", "DarkOrange": "#FF8C00", "Orange": "#FFA500",
    "LightYellow": "#FFFFE0", "PapayaWhip": "#FFEFD5", "White": "#FFFFFF",
    "YellowGreen": "#9ACD32", "LightGreen": "#90EE90",
    "ForestGreen": "#228B22", "Khaki": "#F0E68C",
    "MediumOrchid": "#BA55D3", "MediumPurple": "#9370DB",
    "MistyRose": "#FFE4E1", "LightSeaGreen": "#20B2AA",
    "MediumTurquoise": "#48D1CC", "LightSlateGray": "#778899",
    "Olive": "#808000",
    "WindNotInTarget": "#DBDBC5",   # Color.FromArgb(219, 219, 197)
    "SkyNotValid": "#85AABF",       # Color.FromArgb(133, 170, 191)
}


def _has_recharge(s):
    return (s["RechargeValue"] or 0) > 0


def _is_any_leasing(s):
    return bool(s["IsLeasing"] or s["IsLeasingOnly"] or s["IsFindomestic"])


def _infostrada_color(s):
    return CLR["YellowGreen"] if s["IsBusiness"] else CLR["LightGreen"]


def _wind_color(s):
    if s["IsLandline"] or s["IsFixWirelessAccess"]:
        return _infostrada_color(s)
    if s["IsNotValidForProviderTarget"]:
        return CLR["WindNotInTarget"]
    if s["IsNotImportant"]:
        return CLR["LightGray"]
    kind = s["PaymentKind"]
    if kind == "postpaid":
        if _is_any_leasing(s):
            return CLR["DarkSalmon"] if s["IsBusiness"] else CLR["DarkOrange"]
        return CLR["DarkSalmon"] if s["IsBusiness"] else CLR["Orange"]
    if kind == "prepaid":
        if s["IsLeasingOnly"]:
            return CLR["DarkSalmon"]
        return CLR["LightYellow"] if _has_recharge(s) else CLR["PapayaWhip"]
    return CLR["White"]


def compute_color(s):
    prov = s["Provider"]
    if not prov or prov == "None":
        return CLR["LightGray"]
    if s["IsDeleted"]:
        return CLR["DarkGray"]

    if prov == "H3G":
        if s["PaymentKind"] == "postpaid":
            return CLR["SteelBlue"] if s["IsBusiness"] else CLR["LightSteelBlue"]
        if s["IsLeasingOnly"]:
            return CLR["LightSkyBlue"]
        return CLR["LightBlue"]
    if prov == "Wind":
        return _wind_color(s)
    if prov == "Infostrada":
        return _infostrada_color(s)
    if prov == "Very":
        return CLR["ForestGreen"]
    if prov == "Kena":
        return CLR["Khaki"]
    if prov == "S4Energia":
        return CLR["MediumOrchid"] if s["IsElectricity"] else CLR["MediumPurple"]
    if prov in ("Vodafone", "Tim"):
        return CLR["MistyRose"]
    if prov in ("Sky", "Fastweb"):
        if s["IsNotValidForProviderTarget"] or (
                not (s["IsMobile"] and s["IsMNP"]) and s["PaymentKind"] == "prepaid"):
            return CLR["SkyNotValid"]
        if s["IsLandline"]:
            return CLR["LightSkyBlue"]
        return CLR["LightSeaGreen"] if s["PaymentKind"] == "postpaid" else CLR["MediumTurquoise"]
    if prov == "sms":
        return CLR["LightSlateGray"]
    if prov == "Findomestic":
        return CLR["Olive"]
    # default C#: goto case Wind
    return _wind_color(s)


def _wind_icon(s):
    if s["IsNotValidForProviderTarget"]:
        return "WindTre16NotInTarget"
    if s["IsLandline"] or s["IsFixWirelessAccess"]:
        return "WindTreFwa16"
    if s["IsFindomestic"]:
        return "FindomesticAndReload32x16" if _has_recharge(s) else "Findomestic16"
    if s["IsLeasingOnly"]:
        return "WindTreMobile16"
    if s["IsLeasing"]:
        if _has_recharge(s):
            return "WindTreAndReload32x16"
        return "WindTreBusinessMobile16" if s["IsBusiness"] else "WindTreMobile16"
    return "WindTreBusiness16" if s["IsBusiness"] else "WindTre16"


def compute_icon(s):
    prov = s["Provider"]
    if not prov or prov == "None":
        return "Unknown16"
    if prov == "H3G":
        return "Tre16"
    if prov == "Wind":
        return _wind_icon(s)
    if prov == "Findomestic":
        return "Findomestic16"
    if prov == "Infostrada":
        if s["IsFixWirelessAccess"]:
            return "WindTreFwa16"
        return "WindTreFiberBusiness16" if s["IsBusiness"] else "WindTreFiber16"
    if prov == "Very":
        return "Very16"
    if prov == "Kena":
        return "Kena16"
    if prov == "Ho":
        return "Ho16"
    if prov == "S4Energia":
        return "S4EnergiaElectricity" if s["IsElectricity"] else "S4EnergiaGas"
    if prov == "Vodafone":
        return "Vodafone16"
    if prov == "Tim":
        return "Tim16"
    if prov == "Fastweb":
        return "Sky16NotInTarget" if s["IsNotValidForProviderTarget"] else "SkyMobile16"
    if prov == "Sky":
        if s["IsNotValidForProviderTarget"]:
            return "Sky16NotInTarget"
        return "SkyWifi16" if s["IsLandline"] else "SkyMobile16"
    if prov in ("Iliad", "Tiscali", "Digi", "CoopVoce", "Lyca", "PosteMobile"):
        return f"{prov}16"
    return "Unknown16"


# ── Costruzione report ───────────────────────────────────────────────────────

# Opzioni da non mostrare mai nel report (benefit standard, zero informazione)
IGNORED_OPTION_PREFIXES = ("giga illimitati",)


def _display_options(provider, options_main):
    """Opzione da mostrare sulla card della vendita.

    Infostrada: OptionsMain è un testo unico con le opzioni separate da " - "
    e una coda legale ("Per termini e condizioni…") attaccata all'ultima:
    mostra la prima opzione non ignorata, senza coda.
    Altri provider: OptionsMain è già una singola opzione.
    """
    if not options_main:
        return options_main
    if provider == "Infostrada":
        parts = [p.split(" Per termini")[0].strip().rstrip(":").strip()
                 for p in options_main.split(" - ")]
        parts = [p for p in parts if p]
    else:
        parts = [options_main]
    return next((p for p in parts
                 if not p.lower().startswith(IGNORED_OPTION_PREFIXES)), None)


def _category(s):
    prov, kind = s["Provider"], s["PaymentKind"]
    if prov in ("Wind", "Very") and kind in ("postpaid", "prepaid"):
        return "mobile"
    if prov == "Infostrada":
        return "fisso"
    if prov == "Sky":
        return "sky_m" if s["IsMobile"] else "sky_nm"
    return "altro"


def month_to_date_totals(conn, day):
    """Totali "Attuale (DB)" come generate_dashboard.py (WindTreTargetImporter):
    somma di Contract_Multiplier per categoria dal 1° del mese al giorno del
    report, raggruppando per DATE(DateTime); None se nessuna vendita.
    Sky = sky non-mobile + sky mobile.
    """
    filters = {"mobile": FILTER_MOBILE, "fisso": FILTER_FISSO,
               "sky_nm": FILTER_SKY_NON_MOBILE, "sky_m": FILTER_SKY_MOBILE}
    cases = ",".join(
        f"SUM(CASE WHEN {f} THEN Contract_Multiplier ELSE 0 END),"
        f"COUNT(CASE WHEN {f} THEN 1 END)"
        for f in filters.values())
    cur = conn.cursor()
    cur.execute(
        f"SELECT {cases} FROM Sales WHERE DATE(DateTime) BETWEEN ? AND ?",
        (day.replace(day=1).isoformat(), day.isoformat()))
    row = cur.fetchone()
    t = {c: (row[i * 2] if row[i * 2 + 1] else None)
         for i, c in enumerate(filters)}
    sky = (None if t["sky_nm"] is None and t["sky_m"] is None
           else (t["sky_nm"] or 0) + (t["sky_m"] or 0))
    return {"mobile": t["mobile"], "fisso": t["fisso"], "sky": sky}


def _mese_key(mese_anno):
    """Chiave di ordinamento per 'MM/YY' (come common.py mese_to_number)."""
    mm, yy = mese_anno.split("/")
    return int(yy) * 100 + int(mm)


def _soglie_for_month(cur, table, mese_anno):
    """Soglie del mese dalla tabella indicata; se assenti le proietta dal mese
    più vicino che precede (fallback: successivo), come generate_dashboard.py.
    Ritorna (valori, proiettate)."""
    cur.execute(f"SELECT valore_soglia FROM {table} "
                "WHERE mese_anno = ? ORDER BY numero_soglia", (mese_anno,))
    values = [r[0] for r in cur.fetchall()]
    if values:
        return values, False
    cur.execute(f"SELECT DISTINCT mese_anno FROM {table}")
    mesi = [r[0] for r in cur.fetchall()]
    target = _mese_key(mese_anno)
    prima = [m for m in mesi if _mese_key(m) < target]
    dopo = [m for m in mesi if _mese_key(m) > target]
    ref = (max(prima, key=_mese_key) if prima
           else min(dopo, key=_mese_key) if dopo else None)
    if ref is None:
        return [], False
    cur.execute(f"SELECT valore_soglia FROM {table} "
                "WHERE mese_anno = ? ORDER BY numero_soglia", (ref,))
    return [r[0] for r in cur.fetchall()], True


def month_chart_data(conn, day):
    """Dati per il grafico mensile in stile dashboard: cumulate giornaliere
    per categoria da PagoDealer (stessi filtri di "Attuale (DB)"), punti PDF
    del mese e soglie (reali o proiettate) da avanzamenti.db."""
    start = day.replace(day=1)
    filters = (FILTER_MOBILE, FILTER_FISSO,
               FILTER_SKY_NON_MOBILE, FILTER_SKY_MOBILE)
    cases = ",".join(
        f"SUM(CASE WHEN {f} THEN Contract_Multiplier ELSE 0 END)"
        for f in filters)
    cur = conn.cursor()
    cur.execute(
        f"SELECT DATE(DateTime) AS g, {cases} FROM Sales "
        "WHERE DATE(DateTime) BETWEEN ? AND ? GROUP BY g",
        (start.isoformat(), day.isoformat()))
    per_day = {r[0]: r[1:] for r in cur.fetchall()}

    labels, series = [], {"mobile": [], "fisso": [], "skyNm": [], "skyM": [],
                          "sky": []}
    cum = [0.0, 0.0, 0.0, 0.0]
    d = start
    while d <= day:
        vals = per_day.get(d.isoformat())
        if vals:
            cum = [c + (v or 0) for c, v in zip(cum, vals)]
        labels.append(str(d.day))
        series["mobile"].append(round(cum[0], 2))
        series["fisso"].append(round(cum[1], 2))
        series["skyNm"].append(round(cum[2], 2))
        series["skyM"].append(round(cum[3], 2))
        series["sky"].append(round(cum[2] + cum[3], 2))
        d += dt.timedelta(days=1)

    chart = {"labels": labels, **series, "pdf": None,
             "soglie": {"mobile": {"values": [], "projected": False},
                        "fisso": {"values": [], "projected": False},
                        "sky": {"values": [], "projected": False}}}

    if not AVANZAMENTI_DB.exists():
        return chart

    aconn = sqlite3.connect(f"file:{AVANZAMENTI_DB.as_posix()}?mode=ro",
                            uri=True)
    try:
        acur = aconn.cursor()
        mese_anno = f"{day.month:02d}/{str(day.year)[2:]}"
        for cat, table in (("mobile", "soglie_mobile"),
                           ("fisso", "soglie_fisso"), ("sky", "soglie_sky")):
            values, projected = _soglie_for_month(acur, table, mese_anno)
            chart["soglie"][cat] = {"values": values, "projected": projected}

        # Punti PDF del mese, allineati sulle label giornaliere (null altrove)
        acur.execute(
            "SELECT data_aggiornamento, punti_mobile_actual, "
            "punti_fisso_actual FROM avanzamenti WHERE mese_anno = ? "
            "ORDER BY data_aggiornamento", (mese_anno,))
        rows = acur.fetchall()
        if rows:
            pdf_mob = [None] * len(labels)
            pdf_fis = [None] * len(labels)
            for data_str, mob, fis in rows:
                try:
                    day_idx = int(data_str.split("/")[0]) - 1
                except (ValueError, AttributeError):
                    continue
                if 0 <= day_idx < len(labels):
                    pdf_mob[day_idx] = mob
                    pdf_fis[day_idx] = fis
            chart["pdf"] = {"mobile": pdf_mob, "fisso": pdf_fis}
    finally:
        aconn.close()
    return chart


def last_day_with_sales(conn, upto):
    """Ultimo giorno (<= upto) con almeno una vendita, o None."""
    cur = conn.cursor()
    cur.execute("""
        SELECT MAX(Day) FROM Sales
        WHERE Day <= ? AND IsLatest_Revision = 1 AND IsDeleted = 0
    """, (int(upto.strftime("%Y%m%d")),))
    row = cur.fetchone()[0]
    return dt.datetime.strptime(str(row), "%Y%m%d").date() if row else None


def build_report(conn, day):
    day_int = int(day.strftime("%Y%m%d"))
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM Sales
        WHERE Day = ? AND IsLatest_Revision = 1 AND IsDeleted = 0
    """, (day_int,))
    rows = cur.fetchall()

    # Ordinamento come la griglia del gestionale (ResultsOfDB.cs) ma con le
    # landline in cima: poi provider Z→A (Wind in cima), postpaid prima di
    # prepaid, energia in fondo; a parità, vendita più recente prima.
    # Passate stabili dal criterio meno significativo al più significativo.
    rows.sort(key=lambda s: s["DateTime"] or "", reverse=True)
    rows.sort(key=lambda s: (s["PaymentKind"] or "").lower())
    rows.sort(key=lambda s: (s["Provider"] or "").lower(), reverse=True)
    rows.sort(key=lambda s: bool(s["IsLandline"]), reverse=True)
    rows.sort(key=lambda s: bool(s["IsEnergy"]))

    sales = []
    cat_totals = {c: {"count": 0, "mult": 0.0}
                  for c in ("mobile", "fisso", "sky_nm", "sky_m", "altro")}
    pos_totals, seller_totals = {}, {}
    total_mult = 0.0

    for s in rows:
        mult = float(s["Contract_Multiplier"] or 0)
        cat = _category(s)
        icon = compute_icon(s)
        cat_totals[cat]["count"] += 1
        cat_totals[cat]["mult"] += mult
        total_mult += mult
        for key, bucket in ((s["POSCode"], pos_totals), (s["POSSeller"], seller_totals)):
            k = key or "?"
            bucket.setdefault(k, {"count": 0, "mult": 0.0, "icons": []})
            bucket[k]["count"] += 1
            bucket[k]["mult"] += mult
            bucket[k]["icons"].append(icon)

        leasing = None
        if _is_any_leasing(s):
            leasing = {
                "brand": s["LeasingBrand"],
                "model": s["LeasingModel"],
                "kind": s["Leasing"],
                "value": s["Leasing_Price_Full"],
            }

        contract = s["ContractName"]
        options = _display_options(s["Provider"], s["OptionsMain"])
        # Wind: "New Basic" è il nome contratto generico, non dice nulla.
        if s["Provider"] == "Wind" and contract == "New Basic":
            contract = None

        sales.append({
            "time": (s["DateTime"] or "")[11:16],
            "pos": s["POSCode"],
            "seller": s["POSSeller"],
            "customer": f"{s['Surname'] or ''} {s['Name'] or ''}".strip(),
            "contract": contract,
            "options": options,
            "provider": s["Provider"],
            "kind": s["PaymentKind"],
            "mult": mult,
            "color": compute_color(s),
            "icon": icon,
            "mnp": bool(s["IsMNP"]),
            "business": bool(s["IsBusiness"]),
            "landline": bool(s["IsLandline"]),
            "fwa": bool(s["IsFixWirelessAccess"]),
            "notInTarget": bool(s["IsNotValidForProviderTarget"]),
            "recharge": s["RechargeValue"] if _has_recharge(s) else None,
            "leasing": leasing,
            "category": cat,
        })

    return {
        "version": 1,
        "reportDate": day.isoformat(),
        "generatedAt": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "monthToDate": month_to_date_totals(conn, day),
        "monthChart": month_chart_data(conn, day),
        "totals": {
            "count": len(sales),
            "mult": round(total_mult, 2),
            "byCategory": cat_totals,
            "byPos": pos_totals,
            "bySeller": seller_totals,
        },
        "sales": sales,
    }


# ── Cifratura (AES-256-GCM + PBKDF2-SHA-256) ─────────────────────────────────

def encrypt_report(report, password):
    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=PBKDF2_ITERATIONS)
    key = kdf.derive(password.encode("utf-8"))
    plaintext = json.dumps(report, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(iv, plaintext, None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return {
        "version": 1,
        "algorithm": "AES-GCM",
        "kdf": "PBKDF2-SHA-256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": b64(salt),
        "iv": b64(iv),
        "ciphertext": b64(ciphertext),
    }


def decrypt_report(payload, password):
    """Inverso di encrypt_report; None su qualunque errore (password
    ruotata, file corrotto, formato inatteso)."""
    try:
        salt = base64.b64decode(payload["salt"])
        iv = base64.b64decode(payload["iv"])
        ciphertext = base64.b64decode(payload["ciphertext"])
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                         iterations=payload["iterations"])
        key = kdf.derive(password.encode("utf-8"))
        return json.loads(AESGCM(key).decrypt(iv, ciphertext, None))
    except Exception:
        return None


def report_is_unchanged(report, password):
    """True se OUTPUT_FILE contiene già lo stesso report (generatedAt
    escluso): in quel caso non c'è nulla da ricifrare né da pushare."""
    if not OUTPUT_FILE.exists():
        return False
    try:
        payload = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    old = decrypt_report(payload, password)
    if old is None:
        return False
    strip = lambda r: {k: v for k, v in r.items() if k != "generatedAt"}
    return strip(old) == strip(report)


def get_password(cli_password):
    if cli_password:
        return cli_password
    env = os.getenv("REPORT_PASSWORD")
    if env:
        return env
    if PASSWORD_FILE.exists():
        pw = PASSWORD_FILE.read_text(encoding="utf-8").strip()
        if pw:
            return pw
    sys.exit("Password mancante: usa --password, REPORT_PASSWORD "
             "o il file password.local.txt")


def main():
    ap = argparse.ArgumentParser(description="Genera il report vendite cifrato")
    ap.add_argument("--date", help="Giorno del report (YYYY-MM-DD, default oggi)")
    ap.add_argument("--password", help="Password di cifratura")
    ap.add_argument("--plain", metavar="FILE",
                    help="DEBUG: salva anche il JSON in chiaro (non committare!)")
    ap.add_argument("--force", action="store_true",
                    help="Riscrive il report anche se i dati sono invariati")
    args = ap.parse_args()

    day = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    password = get_password(args.password)

    conn = connect_pagodealer()
    try:
        # Senza --date: se oggi non ci sono vendite, usa l'ultimo
        # giorno che ne ha (es. la domenica mostra il sabato).
        if not args.date:
            fallback = last_day_with_sales(conn, day)
            if fallback and fallback != day:
                print(f"Nessuna vendita il {day.isoformat()}: uso l'ultimo "
                      f"giorno con vendite ({fallback.isoformat()})")
                day = fallback
        report = build_report(conn, day)
    finally:
        conn.close()

    if args.plain:
        Path(args.plain).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"⚠️  JSON in chiaro scritto in {args.plain} (NON committare)")

    if not args.force and report_is_unchanged(report, password):
        print(f"Nessuna variazione rispetto a {OUTPUT_FILE.name}: "
              "report invariato, niente da committare (usa --force per riscriverlo)")
        return

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(encrypt_report(report, password)),
                           encoding="utf-8")
    print(f"Report {day.isoformat()}: {report['totals']['count']} vendite, "
          f"{report['totals']['mult']:.2f} punti → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
