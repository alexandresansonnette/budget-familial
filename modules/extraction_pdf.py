"""
Budget Familial AS — Module extraction PDF (v2.5, étape 4)
Extraction des relevés bancaires PDF (CA, Monabanq…) via pdfplumber.
Porté depuis analyse-comptes : détection de tableaux, détection de
colonnes par en-têtes, fusion des lignes multi-lignes, filtrage des
lignes parasites et des récapitulatifs carte (déjà gérés par l'app).

Retourne des lignes normalisées : {date 'YYYY-MM-DD', libelle, montant, type}
directement compatibles avec le flux d'import (groupement + apprentissage).
"""
import re
from datetime import datetime

_ENTETES = {
    "libellé", "libelle", "opération", "operation", "désignation",
    "désignation de l'opération", "detail", "détail", "description",
    "nature", "intitulé", "intitule",
}
_ENTETES_DATE = {
    "date", "date opération", "date operation", "date valeur",
    "date de valeur", "jour",
}
_ENTETES_MONTANT = {
    "débit", "debit", "crédit", "credit", "montant", "somme",
    "débit €", "crédit €", "débit eur", "crédit eur",
    "débit euros", "crédit euros",
    "mouvements débiteurs", "mouvements créditeurs",
}
# Récapitulatifs carte sur relevé CA : déjà déduits par l'app (règle MC)
_RE_PRLV_CARTE = re.compile(
    r"(factur\w*\s+carte|prlv\s+carte|remise\s+carte|total\s+carte"
    r"|r[eè]glement\s+carte|pr[eé]l[eè]vement\s+carte"
    r"|vos\s+paiements\s+carte|arr[eê]t[eé]\s+carte"
    r"|d[eé]penses\s+carte)",
    re.IGNORECASE,
)
_RE_DATE = re.compile(r"\d{2}")
_RE_MONTANT = re.compile(r"[\d\s]+[.,]\d{2}\s*€?\s*$")
_RE_LIGNE_PARASITE = re.compile(
    r"""(
        \btotal\b | \bfrais\b | \bautorisation\b | \bd[eé]couvert\b
      | \bfacilit[eé]\b | \btaeg\b | \bp[eé]riode\b
      | \bn[°º]\s*de\s*compte\b | \bproduits\s+et\s+services\b
      | \br[eé]capitulatif\b | \bsolde\s+(au|du|de|initial|final)\b
      | \breport[eé]?\b | \bancien\s+solde\b | \bnouveau\s+solde\b
      | \bmontant\s+pr[eé]lev[eé]\b | ^ref\s+vir\b
      | ^[A-Z]{2}\d{2}[A-Z0-9]{10,}
    )""",
    re.IGNORECASE | re.VERBOSE,
)
_RE_VRAIE_DATE = re.compile(
    r"""(
        \d{1,2}[/\.\-]\d{1,2}([/\.\-]\d{2,4})?
      | \d{1,2}\s+(jan|f[eé]v|mar|avr|mai|juin|juil|ao[uû]|sep|oct|nov|d[eé]c)
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def _tableau_est_un_releve(table):
    if not table or len(table) < 2:
        return False
    nb_cols = max(len(r) for r in table if r)
    if nb_cols < 4:
        return False
    header = None
    for row in table[:3]:
        cells = [str(c or "").lower().strip() for c in row]
        if any(c in _ENTETES_DATE for c in cells):
            header = cells
            break
    if header is not None:
        return (any(c in _ENTETES_DATE for c in header)
                and any(c in _ENTETES_MONTANT for c in header))
    lignes_data = [r for r in table if r and len(r) >= 3]
    if not lignes_data:
        return False
    score = sum(
        1 for row in lignes_data
        if bool(_RE_DATE.search(str(row[0] or "").strip()))
        and len(str(row[0] or "").strip()) <= 20
        and any(bool(_RE_MONTANT.search(str(c or ""))) for c in row)
    )
    return (score / len(lignes_data)) >= 0.30


def _detecter_colonnes(header_row):
    idx_date = idx_lib = idx_deb = idx_cred = None
    _DATE_KEYS = {"date", "date opé.", "date ope.", "date opé", "date ope",
                  "date opération", "date operation", "jour"}
    _LIB_KEYS = {"libellé", "libelle", "libellé des opérations",
                 "libelle des operations", "opération", "operation",
                 "désignation", "description", "nature"}
    _DEB_KEYS = {"débit", "debit", "débit €", "débit eur", "débit euros",
                 "mouvements débiteurs"}
    _CRED_KEYS = {"crédit", "credit", "crédit €", "crédit eur",
                  "crédit euros", "mouvements créditeurs"}
    for i, cell in enumerate(header_row):
        c = str(cell or "").lower().strip().replace("\n", " ")
        if c in _DATE_KEYS and idx_date is None:
            idx_date = i
        elif c in _LIB_KEYS and idx_lib is None:
            idx_lib = i
        elif c in _DEB_KEYS and idx_deb is None:
            idx_deb = i
        elif c in _CRED_KEYS and idx_cred is None:
            idx_cred = i
    if idx_deb is not None and idx_cred is None and idx_deb + 1 < len(header_row):
        idx_cred = idx_deb + 1
    if idx_date is None or idx_lib is None or idx_deb is None:
        return None
    return (idx_date, idx_lib, idx_deb, idx_cred)


def _parse_montant(cell):
    s = re.sub(r"[^\d,.]", "", str(cell or "").strip())
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _fusionner_lignes(table, idx_date, idx_lib, idx_deb, idx_cred, header_idx):
    """Fusionne les libellés multi-lignes (suite sans date ni montant)."""
    fusionnees = []
    max_idx = max(c for c in (idx_date, idx_lib, idx_deb, idx_cred)
                  if c is not None)
    for ri, row in enumerate(table):
        if ri <= header_idx:
            continue
        if not row or len(row) <= max_idx:
            continue
        date_cell = str(row[idx_date] or "").strip()
        lib_cell = str(row[idx_lib] or "").strip().replace("\n", " ")
        deb_cell = str(row[idx_deb] or "").strip()
        cred_cell = (str(row[idx_cred] or "").strip()
                     if idx_cred is not None else "")
        est_continuation = (not date_cell and lib_cell
                            and not deb_cell and not cred_cell)
        if est_continuation and fusionnees:
            if not _RE_LIGNE_PARASITE.search(lib_cell):
                fusionnees[-1]["libelle_suite"] = (
                    fusionnees[-1].get("libelle_suite", "") + " " + lib_cell
                ).strip()
        else:
            fusionnees.append({
                "date": date_cell, "libelle": lib_cell,
                "debit_cell": deb_cell, "credit_cell": cred_cell,
                "libelle_suite": "",
            })
    return fusionnees


def _normaliser_date(date_str, annee_defaut=None):
    """'05/06/2026', '05/06/26', '05.06' → 'YYYY-MM-DD' (None si invalide)."""
    s = date_str.strip().replace(".", "/").replace("-", "/")
    parts = s.split("/")
    try:
        if len(parts) == 3:
            j, m, a = int(parts[0]), int(parts[1]), int(parts[2])
            if a < 100:
                a += 2000
        elif len(parts) == 2 and annee_defaut:
            j, m, a = int(parts[0]), int(parts[1]), int(annee_defaut)
        else:
            return None
        return datetime(a, m, j).strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return None


def extraire_releve_pdf(file_obj, annee_defaut=None):
    """
    Extrait les opérations d'un relevé bancaire PDF.
    file_obj : fichier uploadé (Streamlit UploadedFile ou chemin).
    annee_defaut : année à utiliser si les dates du PDF n'en ont pas
                   (certains relevés affichent JJ/MM seulement).
    Retourne (rows, n_carte_ignorees) :
      rows = [{date, libelle, montant, type}] prêt pour le flux d'import.
    """
    import pdfplumber

    rows, n_carte = [], 0
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            for table in (page.extract_tables() or []):
                if not _tableau_est_un_releve(table):
                    continue
                cols = None
                header_idx = 0
                for hi, row in enumerate(table[:3]):
                    cols = _detecter_colonnes(row)
                    if cols:
                        header_idx = hi
                        break
                if not cols:
                    cols = (0, 2, 3, 4)
                idx_date, idx_lib, idx_deb, idx_cred = cols
                lignes = _fusionner_lignes(table, idx_date, idx_lib,
                                           idx_deb, idx_cred, header_idx)
                for ligne in lignes:
                    date_raw = ligne["date"]
                    suite = ligne["libelle_suite"]
                    libelle = (ligne["libelle"]
                               + (" " + suite if suite else "")).strip()
                    if not date_raw or not libelle:
                        continue
                    if not _RE_VRAIE_DATE.search(date_raw):
                        continue
                    if libelle.lower().strip() in _ENTETES:
                        continue
                    if _RE_PRLV_CARTE.search(libelle):
                        n_carte += 1
                        continue
                    if _RE_LIGNE_PARASITE.search(libelle):
                        continue
                    date_norm = _normaliser_date(date_raw, annee_defaut)
                    if not date_norm:
                        continue
                    debit = _parse_montant(ligne["debit_cell"])
                    credit = _parse_montant(ligne["credit_cell"])
                    if debit > 0:
                        rows.append({"date": date_norm, "libelle": libelle,
                                     "montant": debit, "type": "depense"})
                    elif credit > 0:
                        rows.append({"date": date_norm, "libelle": libelle,
                                     "montant": credit, "type": "revenu"})
    return rows, n_carte
