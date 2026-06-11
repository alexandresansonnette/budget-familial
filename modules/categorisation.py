"""
Budget Familial AS — Module catégorisation (v2.5, étape 1)
Registre de mots-clés APPRIS, stocké dans D['cat_keywords'] et persisté
dans Google Sheets avec le reste des données.

Inspiré d'analyse-comptes : extraction d'un « tronc » propre du libellé
bancaire (sans tokens génériques VIR/PRLV/SEPA, sans numéros/IBAN/dates),
mémorisé comme mot-clé lors de la validation manuelle d'une catégorie.
"""
import re

# Tokens bancaires génériques — jamais des mots-clés utiles
_TOKENS_GENERIQUES = re.compile(
    r"""^(
        virement | vir | inst | sepa | prlv | pr[eé]l[eè]vement
      | paiement | psc | tpe | cb | chq | ch[eè]que | ech | cotis
      | r[eè]glement | r[eé]gl | fact | facture
      | carte | vers | de | du | le | la | les | au | aux | et | ou | par | sur
      | m | mr | mme | dr | ag | gestion | [eé]ch[eé]ance | [eé]ch[eé]ances
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

# Tokens « bruit » : numéros, dates, IBAN, références…
_RE_TOKEN_BRUIT = re.compile(
    r"""(
        \d{2}[/.]\d{2,4} | \d{4,} | ^-$
      | \bIBAN\b | \bBIC\b | \bREF\b
      | \bCONTRAT\b | \bECHEANCE\b | \bCOTISATION\b | \bPERIODIQUE\b
      | \bCORE\b | ^FR\d{2} | \*\* | ^[A-Z]{2,4}-\d+$ | ^[A-Z]\d{2,}
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def extraire_tronc(libelle: str, max_mots_utiles: int = 3) -> str:
    """Extrait les mots distinctifs d'un libellé bancaire (ex. marchand)."""
    mots_utiles = []
    for tok in libelle.split():
        if _RE_TOKEN_BRUIT.search(tok) or tok == "-":
            continue
        if _TOKENS_GENERIQUES.match(tok):
            continue
        mots_utiles.append(tok)
        if len(mots_utiles) >= max_mots_utiles:
            break
    return " ".join(mots_utiles)


def guess_cat(D, libelle: str, cats_visibles: list) -> str | None:
    """
    Propose une catégorie depuis le registre appris D['cat_keywords'].
    Retourne None si aucun mot-clé ne matche (→ à valider manuellement).
    Le mot-clé le plus LONG gagne (plus spécifique).
    """
    lib = libelle.upper()
    best_cat, best_len = None, 0
    for cat, mots in D.get("cat_keywords", {}).items():
        for mot in mots:
            if mot.upper() in lib and len(mot) > best_len:
                best_cat, best_len = cat, len(mot)
    if best_cat and best_cat in cats_visibles:
        return best_cat
    return best_cat if best_cat else None


def memoriser_mot_cle(D, categorie: str, mot_cle: str):
    """Ajoute un mot-clé au registre (idempotent, insensible à la casse)."""
    mot = mot_cle.strip().upper()
    if not mot or len(mot) < 3:
        return False
    if "cat_keywords" not in D:
        D["cat_keywords"] = {}
    existants = [m.upper() for m in D["cat_keywords"].get(categorie, [])]
    if mot in existants:
        return False
    D["cat_keywords"].setdefault(categorie, []).append(mot)
    return True


# Amorçage du registre depuis les anciennes règles codées en dur
# (utilisé une seule fois par migrate() si cat_keywords absent)
SEED_KEYWORDS = {
    "ARE / Salaire": ["SALAIRE", "ARE", "ALLOCATION", "CAF", "PRIME"],
    "Nourriture": ["CARREFOUR", "LECLERC", "LIDL", "ALDI", "MONOP",
                   "SUPERMARCHE", "COURSES", "INTERMARCHE", "GRAND FRAIS"],
    "Prêt / Assurance": ["SGFGAS", "CAISSE EPARGNE", "REGROUPEMENT",
                         "GROUPAMA", "PREDICA", "MAAF", "AXA", "COFIDIS"],
    "Voiture": ["SNCF", "RATP", "ESSENCE", "TOTAL", "SHELL", "PEAGE",
                "AUTOROUTE", "VINCI"],
    "Abonnement": ["NETFLIX", "SPOTIFY", "CANAL", "SFR", "BOUYGUES",
                   "AMAZON PRIME", "ICLOUD", "GOOGLE ONE", "CHATGPT",
                   "CLAUDE.AI"],
    "Santé": ["PHARMACIE", "MEDECIN", "DOCTEUR", "HOPITAL", "CLINIQUE",
              "MUTUELLE"],
    "CLAE / École": ["ECOLE", "SCOLAIRE", "CANTINE", "CLAE", "PERISCOLAIRE",
                     "NOTRE DAME"],
    "Sénégal": ["SENEGAL", "WESTERN UNION", "SENDWAVE"],
    "Virement interne": ["VIREMENT EQUILIBRE"],
    "Habit / Beauté": ["ZARA", "H&M", "PRIMARK", "COIFFEUR", "KIABI"],
    "Loisirs / Vacances": ["RESTAURANT", "CINEMA", "HOTEL", "BOOKING"],
    "Impôts / Taxes": ["IMPOT", "DGFIP", "TRESOR PUBLIC"],
}


# ══ v2.5 étape 3 : Opérations OPAQUES ═══════════════════════════════════════
# Chèques, virements P2P (Wero, Paylib, Lydia…) et virements sans tronc
# distinctif : le mot-clé ne généralise pas (destinataire différent à chaque
# fois). On les mémorise INDIVIDUELLEMENT par (date, libellé) dans
# D['ops_connues'] — jamais dans le registre de mots-clés.

_RE_CHEQUE = re.compile(r"^\s*ch[eè]que\s+\d+\s*$", re.IGNORECASE)
_SERVICES_P2P = ("wero", "paylib", "lydia", "sumeria")


def est_cheque(libelle: str) -> bool:
    return bool(_RE_CHEQUE.match(libelle.strip()))


def est_op_opaque(libelle: str) -> bool:
    """
    Virement ou paiement dont le tronc distinctif est vide ou trop vague,
    ou service P2P (destinataire variable). À catégoriser individuellement.
    """
    lib = libelle.strip()
    if est_cheque(lib):
        return True
    if any(s in lib.lower() for s in _SERVICES_P2P):
        return True
    est_vir = bool(re.match(r"^(vir(ement)?\s)", lib, re.IGNORECASE))
    est_paie = bool(re.match(r"^(paiement|psc|cb\s|carte\s)", lib, re.IGNORECASE))
    if not est_vir and not est_paie:
        return False
    tronc = extraire_tronc(lib)
    return not tronc or len(tronc) <= 3


def cle_op(date_str: str, libelle: str) -> str:
    """Clé unique d'une opération opaque : date|libellé normalisé."""
    return f"{date_str}|{libelle.strip().upper()}"


def memoriser_op(D, date_str: str, libelle: str, categorie: str):
    """Mémorise la catégorie d'une opération opaque individuelle."""
    if "ops_connues" not in D:
        D["ops_connues"] = {}
    D["ops_connues"][cle_op(date_str, libelle)] = categorie
