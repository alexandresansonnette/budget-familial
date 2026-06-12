"""Tests des règles métier fondamentales — modules/calculs.py et data.py."""
import pytest
from modules.data import mc_aff_from_date
from modules.calculs import (aff_key, month_add, rec_active,
                             mc_depenses_mois, _rec_deja_couverte,
                             get_sol, set_sol)


# ── Règle MC : date ≥ 25 → mois suivant ──────────────────────────────────────
@pytest.mark.parametrize("date_str,attendu", [
    ("2026-06-24", (5, 2026)),   # 24 juin → juin (0-indexed 5)
    ("2026-06-25", (6, 2026)),   # 25 juin → juillet
    ("2026-12-24", (11, 2026)),  # 24 déc → décembre
    ("2026-12-25", (0, 2027)),   # 25 déc → janvier année suivante
    ("2026-01-01", (0, 2026)),   # 1er janvier → janvier
])
def test_mc_aff_from_date(date_str, attendu):
    assert mc_aff_from_date(date_str) == attendu


# ── aff_key : MC via affM/affY, autres via date réelle ───────────────────────
def test_aff_key_mc_utilise_affectation():
    t = {"compte": "mc", "date": "2026-06-28", "affM": 6, "affY": 2026}
    assert aff_key(t) == (2026, 6)  # juillet, pas juin


def test_aff_key_ca_utilise_date_reelle():
    t = {"compte": "ca", "date": "2026-06-28"}
    assert aff_key(t) == (2026, 5)


# ── month_add ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("m,y,n,attendu", [
    (5, 2026, 1, (6, 2026)),
    (11, 2026, 1, (0, 2027)),    # décembre +1 → janvier
    (0, 2026, -1, (11, 2025)),   # janvier -1 → décembre
    (5, 2026, -6, (11, 2025)),
])
def test_month_add(m, y, n, attendu):
    assert month_add(m, y, n) == attendu


# ── rec_active : cycle de vie (v2.6) ─────────────────────────────────────────
@pytest.mark.parametrize("r,m,y,attendu,cas", [
    ({}, 5, 2026, True, "sans cycle de vie : toujours active"),
    ({"finM": 7, "finY": 2026}, 7, 2026, True, "fin août : active en août"),
    ({"finM": 7, "finY": 2026}, 8, 2026, False, "fin août : inactive en sept"),
    ({"pdM": 6, "pdY": 2026, "paM": 9, "paY": 2026}, 5, 2026, True,
     "pause juil-oct : active en juin"),
    ({"pdM": 6, "pdY": 2026, "paM": 9, "paY": 2026}, 7, 2026, False,
     "pause juil-oct : inactive en août"),
    ({"pdM": 6, "pdY": 2026, "paM": 9, "paY": 2026}, 10, 2026, True,
     "pause juil-oct : réactivée en novembre"),
    ({"pdM": 6, "pdY": 2026}, 6, 2026, False,
     "suspension indéfinie : inactive dès juillet"),
    ({"pdM": 6, "pdY": 2026}, 3, 2027, False,
     "suspension indéfinie : toujours inactive en 2027"),
])
def test_rec_active(r, m, y, attendu, cas):
    assert rec_active(r, m, y) == attendu, cas


# ── mc_depenses_mois : affectation + filtre date réelle ─────────────────────
def test_mc_depenses_mois():
    tx = [
        {"compte": "mc", "type": "depense", "montant": 100.0,
         "date": "2026-06-10", "affM": 5, "affY": 2026},
        {"compte": "mc", "type": "depense", "montant": 50.0,
         "date": "2026-06-28", "affM": 6, "affY": 2026},  # affecté juillet
        {"compte": "ca", "type": "depense", "montant": 999.0,
         "date": "2026-06-10"},  # pas MC
    ]
    assert mc_depenses_mois(tx, 5, 2026) == 100.0
    assert mc_depenses_mois(tx, 6, 2026) == 50.0


# ── Matching récurrente ↔ TX réelle (±2 % sur le montant) ───────────────────
def test_rec_deja_couverte():
    r = {"type": "depense", "mnt": 100.0}
    assert _rec_deja_couverte(r, [{"type": "depense", "montant": 101.0}])
    assert not _rec_deja_couverte(r, [{"type": "depense", "montant": 110.0}])
    assert not _rec_deja_couverte(r, [{"type": "revenu", "montant": 100.0}])


# ── Soldes get/set ───────────────────────────────────────────────────────────
def test_get_set_sol():
    sol = {}
    set_sol(sol, "ca", 5, 2026, 1234.56)
    assert get_sol(sol, "ca", 5, 2026) == 1234.56
    assert get_sol(sol, "ca", 6, 2026) is None
    set_sol(sol, "ca", 5, 2026, None)  # suppression
    assert get_sol(sol, "ca", 5, 2026) is None
