"""
Budget Familial AS — Module prévision
Calculs prévisionnels basés sur une source unique : les TX réelles.

Règles :
- Passé : TX réelles groupées par mois d'affectation
- Futur : récurrentes + budget cible (moyenne pondérée si historique suffisant)
- MC : intégrée dans CA (débit différé)
- Virements internes / Épargne : exclus des barres (neutres pour le foyer)
"""
import numpy as np
from datetime import datetime
from collections import defaultdict
from modules.data import CATS_NEUTRES, CATS_REVENUS
from modules.calculs import aff_key, month_add, resolve_sol, mc_depenses_mois


MOIS_COURT = ['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc']


def mois_label(m, y):
    return f"{MOIS_COURT[m]} {y}"


def build_monthly_data(D, cpt_id, n_past=6, n_future=5):
    """
    Construit les données mensuelles pour un compte sur n_past + 1 + n_future mois.
    
    Retourne une liste de dicts :
    {
        'label': str,
        'm': int, 'y': int,
        'entrees': float,      # revenus réels ou estimés (hors neutres)
        'sorties': float,      # dépenses réelles ou estimées (hors neutres, MC incluse sur CA)
        'sol_fin': float|None, # solde fin de mois
        'is_fc': bool,         # True = prévisionnel
    }
    """
    now = datetime.now()
    cm, cy = now.month - 1, now.year

    months = [month_add(cm, cy, i) for i in range(-n_past, n_future + 1)]
    rows = []

    # Solde de départ : début du mois le plus ancien
    start_m, start_y = months[0]
    sol_debut, _ = resolve_sol(D, cpt_id, start_m, start_y)
    sol_courant = sol_debut or 0.0

    # Budget cible pour ce compte
    budget_cible = D.get('budget_cible', {}).get(cpt_id, {})
    revenu_cible = float(D.get('revenu_cible', {}).get(cpt_id, 0))

    # Calcul de la moyenne historique pour les dépenses variables (6 mois passés)
    hist_dep = _build_hist_dep(D, cpt_id, cm, cy, n_past)
    hist_rev = _build_hist_rev(D, cpt_id, cm, cy, n_past)

    for idx, (m, y) in enumerate(months):
        rel = idx - n_past  # -6..0..+5
        is_fc = rel > 0
        label = mois_label(m, y)

        if not is_fc:
            # ── PASSÉ + mois courant : TX réelles ────────────────────────
            entrees, sorties = _real_month(D, cpt_id, m, y)
            sol_courant += entrees - sorties
            sol_fin = round(sol_courant, 2)
        else:
            # ── FUTUR : estimation ────────────────────────────────────────
            entrees = _estimate_rev(D, cpt_id, hist_rev, revenu_cible)
            sorties = _estimate_dep(D, cpt_id, hist_dep, budget_cible, m)
            sol_courant += entrees - sorties
            sol_fin = round(sol_courant, 2)

        rows.append({
            'label': label, 'm': m, 'y': y,
            'entrees': round(entrees, 2),
            'sorties': round(sorties, 2),
            'sol_fin': sol_fin,
            'is_fc': is_fc,
        })

    return rows, sol_debut


def _real_month(D, cpt_id, m, y):
    """Entrées et sorties réelles d'un mois (hors neutres)."""
    tx_m = [t for t in D['tx']
            if t['compte'] == cpt_id
            and aff_key(t) == (y, m)
            and t.get('categorie') not in CATS_NEUTRES]
    entrees = sum(t['montant'] for t in tx_m if t['type'] == 'revenu')
    sorties = sum(t['montant'] for t in tx_m if t['type'] == 'depense')

    # Pour CA : ajouter les dépenses MC affectées à ce mois
    if cpt_id == 'ca':
        mc_tx = [t for t in D['tx']
                 if t['compte'] == 'mc'
                 and t['type'] == 'depense'
                 and aff_key(t) == (y, m)
                 and t.get('categorie') not in CATS_NEUTRES]
        sorties += sum(t['montant'] for t in mc_tx)

    return entrees, sorties


def _build_hist_dep(D, cpt_id, cm, cy, n_past):
    """Historique mensuel des dépenses variables (hors récurrentes, hors exceptionnels)."""
    hist = []
    for i in range(1, n_past + 1):
        pm, py = month_add(cm, cy, -i)
        tx_m = [t for t in D['tx']
                if t['compte'] == cpt_id
                and aff_key(t) == (py, pm)
                and t['type'] == 'depense'
                and not t.get('exceptionnel', False)
                and t.get('categorie') not in CATS_NEUTRES]
        if cpt_id == 'ca':
            tx_m += [t for t in D['tx']
                     if t['compte'] == 'mc'
                     and t['type'] == 'depense'
                     and aff_key(t) == (py, pm)
                     and not t.get('exceptionnel', False)
                     and t.get('categorie') not in CATS_NEUTRES]
        if tx_m:
            hist.append(sum(t['montant'] for t in tx_m))
    return hist


def _build_hist_rev(D, cpt_id, cm, cy, n_past):
    """Historique mensuel des revenus variables (hors récurrentes, hors exceptionnels)."""
    hist = []
    for i in range(1, n_past + 1):
        pm, py = month_add(cm, cy, -i)
        tx_m = [t for t in D['tx']
                if t['compte'] == cpt_id
                and aff_key(t) == (py, pm)
                and t['type'] == 'revenu'
                and not t.get('exceptionnel', False)
                and t.get('categorie') not in CATS_NEUTRES]
        if tx_m:
            hist.append(sum(t['montant'] for t in tx_m))
    return hist


def _estimate_rev(D, cpt_id, hist_rev, revenu_cible):
    """Estime les revenus futurs."""
    rec_rev = sum(r['mnt'] for r in D['rec']
                  if r['compte'] == cpt_id and r['type'] == 'revenu')

    if hist_rev:
        # Filtre IQR
        hist_filt = _iqr_filter(hist_rev)
        if hist_filt:
            w = np.exp(-0.2 * np.arange(len(hist_filt) - 1, -1, -1))
            avg_var = float(np.average(hist_filt, weights=w))
        else:
            avg_var = float(np.median(hist_rev))
    else:
        avg_var = 0.0

    # Fusion avec revenu cible
    if revenu_cible > 0:
        n = len(hist_rev)
        w_cible = max(0.0, (12 - n) / 12)
        avg_var = (1 - w_cible) * avg_var + w_cible * revenu_cible

    return rec_rev + avg_var


def _estimate_dep(D, cpt_id, hist_dep, budget_cible, target_m):
    """Estime les dépenses futures."""
    rec_dep = sum(r['mnt'] for r in D['rec']
                  if r['compte'] == cpt_id and r['type'] == 'depense')
    if cpt_id == 'ca':
        rec_dep += sum(r['mnt'] for r in D['rec']
                       if r['compte'] == 'mc' and r['type'] == 'depense')

    if hist_dep:
        hist_filt = _iqr_filter(hist_dep)
        if hist_filt:
            w = np.exp(-0.2 * np.arange(len(hist_filt) - 1, -1, -1))
            avg_var = float(np.average(hist_filt, weights=w))
        else:
            avg_var = float(np.median(hist_dep))
    else:
        avg_var = 0.0

    # Fusion avec budget cible
    cible_total = sum(budget_cible.values())
    if cible_total > 0:
        n = len(hist_dep)
        w_cible = max(0.0, (12 - n) / 12)
        avg_var = (1 - w_cible) * avg_var + w_cible * cible_total

    return rec_dep + avg_var


def _iqr_filter(vals):
    """Filtre IQR — retire les outliers."""
    if len(vals) < 4:
        return vals
    arr = np.array(vals)
    q1, q3 = np.percentile(arr, 25), np.percentile(arr, 75)
    iqr = q3 - q1
    return [v for v in vals if q1 - 1.5 * iqr <= v <= q3 + 1.5 * iqr]


def agreger_foyer(rows_ca, rows_mb):
    """
    Agrège CA + MB pour la vue foyer.
    Solde recalculé depuis les barres pour cohérence.
    """
    result = []
    for a, b in zip(rows_ca, rows_mb):
        entrees = a['entrees'] + b['entrees']
        sorties = a['sorties'] + b['sorties']
        # Solde foyer = somme des soldes individuels
        sol = None
        if a['sol_fin'] is not None and b['sol_fin'] is not None:
            sol = round(a['sol_fin'] + b['sol_fin'], 2)
        result.append({
            'label':   a['label'], 'm': a['m'], 'y': a['y'],
            'entrees': round(entrees, 2),
            'sorties': round(sorties, 2),
            'sol_fin': sol,
            'is_fc':   a['is_fc'],
        })
    return result
