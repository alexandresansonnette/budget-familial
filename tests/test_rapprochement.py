"""Tests du rapprochement bancaire à l'import (v2.7)."""
from pages.transactions import _rapprocher_releve, _is_releve_mc


def _D():
    return {"tx": [
        {"id": "t1", "date": "2026-06-06", "compte": "ca", "categorie": "Nourriture",
         "montant": 62.40, "type": "depense", "note": "courses"},
        {"id": "t2", "date": "2026-06-12", "compte": "ca", "categorie": "Santé",
         "montant": 25.00, "type": "depense", "note": "pharmacie"},
        {"id": "t3", "date": "2026-06-15", "compte": "ca", "categorie": "Voiture",
         "montant": 48.00, "type": "depense", "note": "essence (montant erroné)"},
        {"id": "t4", "date": "2026-06-06", "compte": "mb", "categorie": "Nourriture",
         "montant": 62.40, "type": "depense", "note": "autre compte"},
    ]}


_RELEVE = [
    {"date": "2026-06-06", "libelle": "PAIEMENT CB CARREFOUR", "montant": 62.40, "type": "depense"},
    {"date": "2026-06-14", "libelle": "PHARMACIE LAFAYETTE", "montant": 25.00, "type": "depense"},
    {"date": "2026-06-15", "libelle": "TOTAL ENERGIES", "montant": 45.00, "type": "depense"},
    {"date": "2026-06-20", "libelle": "PRLV SEPA NETFLIX", "montant": 17.99, "type": "depense"},
]


def test_rapprochement_complet():
    certains, probables, restants, absentes = _rapprocher_releve(_RELEVE, _D(), "ca")
    # Libellés différents mais montant+date identiques → certain
    assert len(certains) == 1 and certains[0][1]["id"] == "t1"
    # Écart de 2 jours → probable
    assert len(probables) == 1 and probables[0][1]["id"] == "t2"
    assert probables[0][2] == 2
    # Montant différent (48 vs 45) + jamais saisi → import normal
    assert {r["libelle"] for r in restants} == {"TOTAL ENERGIES", "PRLV SEPA NETFLIX"}
    # La saisie erronée ressort comme absente du relevé
    assert len(absentes) == 1 and absentes[0]["id"] == "t3"


def test_rapprochement_ignore_autres_comptes():
    certains, _, _, absentes = _rapprocher_releve(_RELEVE, _D(), "ca")
    ids = {t["id"] for _, t, _ in certains} | {t["id"] for t in absentes}
    assert "t4" not in ids


def test_rapprochement_une_tx_un_seul_match():
    # Deux lignes de relevé identiques, une seule TX → un certain + un restant
    releve = [
        {"date": "2026-06-06", "libelle": "CARREFOUR", "montant": 62.40, "type": "depense"},
        {"date": "2026-06-06", "libelle": "CARREFOUR", "montant": 62.40, "type": "depense"},
    ]
    certains, probables, restants, _ = _rapprocher_releve(releve, _D(), "ca")
    assert len(certains) == 1 and len(restants) == 1


def test_garde_fou_releve_mc():
    assert _is_releve_mc("PRELEVEMENT MASTERCARD DEBIT DIFFERE")
    assert _is_releve_mc("RELEVE CARTE 4521")
    assert not _is_releve_mc("PAIEMENT CB CARREFOUR")
