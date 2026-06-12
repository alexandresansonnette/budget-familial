"""Tests catégorisation apprise (v2.5) et prévisionnel (v2.2-v2.4)."""
import pytest
from modules.categorisation import (extraire_tronc, guess_cat,
                                    memoriser_mot_cle, est_op_opaque,
                                    est_cheque, cle_op, memoriser_op,
                                    SEED_KEYWORDS)
from modules.prevision import _iqr_filter, _apprentissage, _estimate_dep


# ── Extraction du tronc ──────────────────────────────────────────────────────
@pytest.mark.parametrize("libelle,attendu", [
    ("PRLV SEPA NETFLIX REF 4521ABC ECHEANCE 05/06", "NETFLIX"),
    ("PAIEMENT CB CARREFOUR AUCH", "CARREFOUR AUCH"),
    ("VIR FACTURE 250119", ""),  # que du bruit → tronc vide
])
def test_extraire_tronc(libelle, attendu):
    assert extraire_tronc(libelle) == attendu


# ── Registre appris : reconnaissance et apprentissage ────────────────────────
def _D():
    return {"cat_keywords": {k: list(v) for k, v in SEED_KEYWORDS.items()}}


def test_guess_cat_reconnu():
    cats = ["Nourriture", "Abonnement", "Divers"]
    assert guess_cat(_D(), "PAIEMENT CB CARREFOUR AUCH", cats) == "Nourriture"


def test_guess_cat_inconnu_puis_appris():
    D, cats = _D(), ["Nourriture", "Divers"]
    assert guess_cat(D, "PRLV BOULANGERIE MARTIN", cats) is None
    assert memoriser_mot_cle(D, "Divers", "BOULANGERIE MARTIN")
    assert guess_cat(D, "PRLV BOULANGERIE MARTIN", cats) == "Divers"
    # Idempotence
    assert not memoriser_mot_cle(D, "Divers", "boulangerie martin")


def test_guess_cat_mot_le_plus_long_gagne():
    D = {"cat_keywords": {"Abonnement": ["GOOGLE"],
                          "Divers": ["GOOGLE CLOUD"]}}
    assert guess_cat(D, "PRLV GOOGLE CLOUD EUROPE", ["Abonnement", "Divers"]) == "Divers"


# ── Opérations opaques ───────────────────────────────────────────────────────
@pytest.mark.parametrize("libelle,attendu", [
    ("CHEQUE 4521678", True),
    ("VIR INST WERO M DUPONT", True),
    ("PAIEMENT PAYLIB JEAN", True),
    ("VIR FACTURE 250119", True),             # tronc vide → opaque
    ("VIR SEPA SALAIRE NDEYE ENTREPRISE", False),
    ("PAIEMENT CB CARREFOUR AUCH", False),
    ("PRLV SEPA NETFLIX", False),
])
def test_est_op_opaque(libelle, attendu):
    assert est_op_opaque(libelle) == attendu


def test_memoire_individuelle_ops():
    D = {}
    memoriser_op(D, "2026-06-03", "CHEQUE 4521678", "CLAE / École")
    assert D["ops_connues"][cle_op("2026-06-03", "CHEQUE 4521678")] == "CLAE / École"


# ── Filtre IQR ───────────────────────────────────────────────────────────────
def test_iqr_filter_retire_outlier():
    vals = [5050, 9000, 5020, 5060, 5040]
    assert 9000 not in _iqr_filter(vals)


def test_iqr_filter_petit_echantillon_intact():
    assert _iqr_filter([100, 5000]) == [100, 5000]  # < 4 valeurs


# ── Apprentissage borné (v2.4) ───────────────────────────────────────────────
def test_apprentissage_converge_vers_derive_reelle():
    est, corr, _ = _apprentissage(5000, [5075, 5090, 5082, 5078])
    assert 5030 < est < 5060  # ~50 % de l'écart ~80


def test_apprentissage_protege_du_mois_fou():
    est, _, _ = _apprentissage(5000, [5050, 9000, 5020, 5060])
    assert est < 5100  # outlier filtré par IQR


def test_apprentissage_borne_a_15_pourcent():
    est, corr, _ = _apprentissage(5000, [8000, 8000, 8000, 8000])
    assert est == pytest.approx(5000 + 0.5 * 0.15 * 5000)  # 5375


def test_apprentissage_inactif_sous_3_mois():
    est, corr, _ = _apprentissage(5000, [6000, 6200])
    assert est == 5000 and corr == 0.0


# ── Estimation dépenses : plan, neutres, cycle de vie ────────────────────────
def _D_prev():
    return {
        "tx": [],
        "rec": [
            {"compte": "ca", "type": "depense", "mnt": 500.0, "cat": "Prêt / Assurance"},
            {"compte": "ca", "type": "depense", "mnt": 1000.0, "cat": "Virement interne"},
            {"compte": "mc", "type": "depense", "mnt": 15.0, "cat": "Abonnement"},
            {"compte": "ca", "type": "depense", "mnt": 200.0, "cat": "Divers",
             "pdM": 5, "pdY": 2026},  # suspendue depuis juin 2026
        ],
        "budget_cible": {"ca": {"Nourriture": 300.0}},
        "revenu_cible": {"ca": 0},
    }


def test_estimate_dep_plan_exclut_neutres_et_suspendues():
    # Juillet 2026 : 500 (prêt) + 15 (MC) + 300 (cible)
    # — le virement neutre (1000) et la récurrente suspendue (200) sont exclus
    est = _estimate_dep(_D_prev(), "ca", [], {"Nourriture": 300.0}, 6, 2026)
    assert est == pytest.approx(815.0)


def test_estimate_dep_recurrente_active_avant_pause():
    # Mai 2026 : la récurrente suspendue (dès juin) est encore active → +200
    est = _estimate_dep(_D_prev(), "ca", [], {"Nourriture": 300.0}, 4, 2026)
    assert est == pytest.approx(1015.0)
