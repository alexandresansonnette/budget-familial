"""
Budget Familial AS — Module données
Chargement / sauvegarde Google Sheets + structure canonique
"""
import json
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

GSHEET_NAME = "Budget Familial AS"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COMPTES = {
    "ca": {"label": "Crédit Agricole", "color": "#378ADD", "bg": "#E6F1FB"},
    "mc": {"label": "Mastercard",      "color": "#BA7517", "bg": "#FAEEDA"},
    "mb": {"label": "Monabanq",        "color": "#1D9E75", "bg": "#E1F5EE"},
}

CATS_NEUTRES = {"Virement interne", "Épargne"}
CATS_REVENUS = {"ARE / Salaire", "Allocations", "Revenu freelance"}

CATS_DEFAULT = sorted([
    "ARE / Salaire", "Allocations", "Revenu freelance", "Prêt / Assurance",
    "Frais divers", "Nourriture", "Habit / Beauté", "Santé", "Sénégal",
    "CLAE / École", "Loisirs / Vacances", "Voiture", "Abonnement", "Tontine",
    "Épargne", "Virement interne", "Impôts / Taxes", "Divers",
])

BUDGET_CIBLE_DEFAULT = {
    "ca": {
        "Nourriture": 108, "Frais divers": 170, "Habit / Beauté": 19,
        "Loisirs / Vacances": 621, "CLAE / École": 1, "Voiture": 0,
        "Abonnement": 0, "Santé": 48, "Sénégal": 0, "Divers": 500,
    },
    "mb": {
        "Nourriture": 319, "Frais divers": 40, "Habit / Beauté": 65,
        "Loisirs / Vacances": 266, "CLAE / École": 339, "Voiture": 130,
        "Abonnement": 0, "Santé": 66, "Sénégal": 218, "Divers": 400,
        "Prêt / Assurance": 335,
    },
}


def get_default_data():
    return {
        "tx": [],
        "cats": [{"nom": c, "visible": True} for c in CATS_DEFAULT],
        "rec": [],
        "prets": [],
        "sol": {},
        "overdraft": {"ca": 500, "mc": 0, "mb": 250},
        "budget_cible": BUDGET_CIBLE_DEFAULT,
        "revenu_cible": {"ca": 0, "mb": 0},
    }


@st.cache_resource
def get_gsheet_client():
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def load_from_gsheet():
    try:
        client = get_gsheet_client()
        sh = client.open(GSHEET_NAME)
        ws = sh.worksheet("data")
        values = ws.col_values(1)
        if values:
            payload = "".join(values)
            data = json.loads(payload)
            return migrate(data)
    except Exception as e:
        st.warning(f"Impossible de charger depuis Google Sheets : {e}")
    return get_default_data()


def save_to_gsheet(data):
    try:
        client = get_gsheet_client()
        sh = client.open(GSHEET_NAME)
        try:
            ws = sh.worksheet("data")
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title="data", rows=2000, cols=2)

        payload = json.dumps(data, ensure_ascii=False)
        chunks = [payload[i:i+40000] for i in range(0, len(payload), 40000)]

        # Écriture sécurisée via onglet tampon
        try:
            ws_tmp = sh.worksheet("data_tmp")
            ws_tmp.clear()
        except gspread.WorksheetNotFound:
            ws_tmp = sh.add_worksheet(title="data_tmp", rows=2000, cols=2)

        ws_tmp.update(
            range_name=f"A1:A{len(chunks)}",
            values=[[c] for c in chunks]
        )

        # Lecture de contrôle
        readback = "".join(ws_tmp.col_values(1))
        check = json.loads(readback)
        if len(check.get("tx", [])) != len(data.get("tx", [])):
            raise ValueError(
                f"Contrôle échoué : {len(check.get('tx',[]))} TX relues "
                f"vs {len(data.get('tx',[]))} attendues"
            )

        # Écriture définitive
        ws.clear()
        ws.update(
            range_name=f"A1:A{len(chunks)}",
            values=[[c] for c in chunks]
        )
        st.session_state["last_save_ok"] = datetime.now().strftime("%d/%m/%Y %H:%M")

    except Exception as e:
        st.error(f"❌ Erreur sauvegarde : {e}")
        st.warning("⚠️ Exportez un JSON de secours immédiatement.")


def migrate(data):
    """Migration vers la structure v2 propre."""
    # Cats : convertir liste de strings si nécessaire
    if data.get("cats") and isinstance(data["cats"][0], str):
        data["cats"] = [{"nom": c, "visible": True} for c in data["cats"]]

    # Supprimer recId des TX (les récurrentes ne créent plus de TX)
    for t in data.get("tx", []):
        t.pop("recId", None)

    # Calculer affM/affY MC uniquement si absent (ne pas écraser les affectations manuelles)
    for t in data.get("tx", []):
        if t.get("compte") == "mc" and (t.get("affM") is None or t.get("affY") is None):
            t["affM"], t["affY"] = mc_aff_from_date(t["date"])

    # Clés manquantes
    if "budget_cible" not in data:
        data["budget_cible"] = BUDGET_CIBLE_DEFAULT
    if "revenu_cible" not in data:
        data["revenu_cible"] = {"ca": 0, "mb": 0}
    if "overdraft" not in data:
        data["overdraft"] = {"ca": 500, "mc": 0, "mb": 250}

    return data


def mc_aff_from_date(date_str):
    """
    Calcule le mois d'affectation MC depuis la date réelle.
    Règle : date >= 25 → mois suivant, date <= 24 → mois courant.
    Retourne (affM, affY) avec affM 0-indexed.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d")
    if d.day >= 25:
        # Mois suivant
        if d.month == 12:
            return 0, d.year + 1
        return d.month, d.year   # month = mois suivant 0-indexed (ex: juin=5 → juillet=6 mais 0-indexed=6)
    else:
        return d.month - 1, d.year


def visible_cats(data):
    return sorted([c["nom"] for c in data["cats"] if c.get("visible", True)])


def all_cats(data):
    return sorted([c["nom"] for c in data["cats"]])
