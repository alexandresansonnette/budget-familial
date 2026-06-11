"""
Budget Familial AS — Module prévision
Calculs prévisionnels basés sur une source unique : les TX réelles.

Règles :
- Passé : TX réelles groupées par mois d'affectation, ancrées sur soldes saisis
- Futur : récurrentes + budget cible (moyenne pondérée si historique suffisant)
- MC : intégrée dans CA (débit différé)
- Virements internes / Épargne : exclus des barres (neutres pour le foyer)
  mais INCLUS dans la propagation du solde (ils bougent réellement l'argent)
- Mois courant : ancré sur projection_fin_mois (récurrentes restantes
  + prélèvement MC inclus) — cohérent avec le cockpit Aujourd'hui
"""
import numpy as np
from datetime import datetime
from collections import defaultdict
from modules.data import CATS_NEUTRES, CATS_REVENUS
from modules.calculs import (
    aff_key, month_add, resolve_sol, mc_depenses_mois, get_sol,
    solde_bancaire, projection_fin_mois, _mvt_net
)


MOIS_COURT = ['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc']


def mois_label(m, y):
    return f"{MOIS_COURT[m]} {y}"


def build_monthly_data(D, cpt_id, n_past=6, n_future=5):
    """
    Construit les données mensuelles pour un compte sur n_past + 1 + n_future mois.

    Passé : pour chaque mois, on réancre sur le solde saisi si disponible,
            puis on propage via le mouvement net RÉEL (_mvt_net — toutes TX,
            y compris neutres) pour obtenir sol_fin.
    Mois courant : sol_fin = projection complète fin de mois
            (solde bancaire ancré + récurrentes restantes + prélèvement MC).
    Futur : on part de cette projection, puis on estime
            via récurrentes + historique.

    Retourne une liste de dicts :
    {
        'label': str,
        'm': int, 'y': int,
        'entrees': float,
        'sorties': float,
        'sol_fin': float|None,
        'is_fc': bool,
    }
    """
    now = datetime.now()
    cm, cy = now.month - 1, now.year

    months = [month_add(cm, cy, i) for i in range(-n_past, n_future + 1)]
    rows = []

    # Budget cible pour ce compte
    budget_cible = D.get('budget_cible', {}).get(cpt_id, {})
    revenu_cible = float(D.get('revenu_cible', {}).get(cpt_id, 0))

    # Historique pour estimation future
    hist_dep = _build_hist_dep(D, cpt_id, cm, cy, n_past)
    hist_rev = _build_hist_rev(D, cpt_id, cm, cy, n_past)

    # Solde propagé — initialisé sur le premier mois
    start_m, start_y = months[0]
    sol_propage, _ = resolve_sol(D, cpt_id, start_m, start_y)
    sol_propage = sol_propage or 0.0

    for idx, (m, y) in enumerate(months):
        rel = idx - n_past  # -6..0..+5
        is_fc = rel > 0
        label = mois_label(m, y)

        if not is_fc:
            # ── PASSÉ + mois courant ──────────────────────────────────────
            # Réancrage : si un solde de début est saisi pour ce mois, on l'utilise
            sol_ancre = get_sol(D['sol'], cpt_id, m, y)
            if sol_ancre is not None:
                sol_debut = sol_ancre
            else:
                sol_debut = sol_propage  # propagé depuis le mois précédent

            # Barres : hors neutres (foyer) + tout inclus (détail par compte)
            entrees, sorties = _real_month(D, cpt_id, m, y)
            entrees_tot, sorties_tot = _real_month(D, cpt_id, m, y,
                                                   include_neutres=True)

            if m == cm and y == cy:
                # ── Mois courant : projection complète fin de mois ────────
                # (récurrentes restantes + prélèvement MC inclus)
                # → cohérent avec le cockpit Aujourd'hui
                proj = projection_fin_mois(D, cpt_id)
                if proj["solde_fin"] is not None:
                    sol_fin = round(proj["solde_fin"], 2)
                else:
                    sol_fin = round(sol_debut + _mvt_net(D, cpt_id, m, y), 2)
            else:
                # ── Mois passé : propagation sur mouvement net réel ───────
                # _mvt_net inclut TOUTES les TX (y compris virements internes
                # et épargne) + déduit la MC pour CA — contrairement aux
                # barres qui excluent les neutres pour la lisibilité.
                sol_fin = round(sol_debut + _mvt_net(D, cpt_id, m, y), 2)

            sol_propage = sol_fin  # pour le mois suivant si pas d'ancrage

        else:
            # ── FUTUR : estimation depuis sol_propage ─────────────────────
            # FIX v2.2c : les barres excluent les récurrentes neutres
            # (Virement interne, Épargne) — cohérent avec le passé.
            # MAIS le flux neutre reste appliqué au solde par compte :
            # un virement CA→MB diminue bien le solde CA et augmente MB.
            entrees = _estimate_rev(D, cpt_id, hist_rev, revenu_cible, m, y)
            sorties = _estimate_dep(D, cpt_id, hist_dep, budget_cible, m, y)
            # Récurrentes neutres (virements internes, épargne) ACTIVES
            rec_neutre_rev = sum(r['mnt'] for r in D['rec']
                                 if r['compte'] == cpt_id
                                 and r['type'] == 'revenu'
                                 and r.get('cat') in CATS_NEUTRES
                                 and rec_active(r, m, y))
            rec_neutre_dep = sum(r['mnt'] for r in D['rec']
                                 if r['compte'] == cpt_id
                                 and r['type'] == 'depense'
                                 and r.get('cat') in CATS_NEUTRES
                                 and rec_active(r, m, y))
            entrees_tot = entrees + rec_neutre_rev
            sorties_tot = sorties + rec_neutre_dep
            flux_neutre = rec_neutre_rev - rec_neutre_dep
            sol_fin = round(sol_propage + entrees - sorties + flux_neutre, 2)
            sol_propage = sol_fin

        rows.append({
            'label': label, 'm': m, 'y': y,
            'entrees': round(entrees, 2),
            'sorties': round(sorties, 2),
            'entrees_tot': round(entrees_tot, 2),
            'sorties_tot': round(sorties_tot, 2),
            'sol_fin': sol_fin,
            'is_fc': is_fc,
        })

    return rows, get_sol(D['sol'], cpt_id, cm, cy)


def _real_month(D, cpt_id, m, y, include_neutres=False):
    """
    Entrées et sorties réelles d'un mois — pour les BARRES.
    include_neutres=False : hors neutres (vue FOYER, virements s'annulent)
    include_neutres=True  : tout inclus (vue DÉTAIL PAR COMPTE — un virement
                            CA→MB est un vrai flux pour chaque compte)
    """
    tx_m = [t for t in D['tx']
            if t['compte'] == cpt_id
            and aff_key(t) == (y, m)
            and (include_neutres or t.get('categorie') not in CATS_NEUTRES)]
    entrees = sum(t['montant'] for t in tx_m if t['type'] == 'revenu')
    sorties = sum(t['montant'] for t in tx_m if t['type'] == 'depense')

    # Pour CA : ajouter les dépenses MC affectées à ce mois
    if cpt_id == 'ca':
        mc_tx = [t for t in D['tx']
                 if t['compte'] == 'mc'
                 and t['type'] == 'depense'
                 and aff_key(t) == (y, m)
                 and (include_neutres or t.get('categorie') not in CATS_NEUTRES)]
        sorties += sum(t['montant'] for t in mc_tx)

    return entrees, sorties


def _build_hist_dep(D, cpt_id, cm, cy, n_past):
    """Historique mensuel des dépenses réelles (hors neutres)."""
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
    """Historique mensuel des revenus réels (hors neutres)."""
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


def _rec_neutre_net(D, cpt_id, m=None, y=None):
    """
    Flux net mensuel des récurrentes NEUTRES (Virement interne, Épargne)
    pour un compte. Exclu des barres d'affichage mais appliqué au solde :
    un virement CA→MB diminue réellement le solde CA et augmente MB.
    """
    if m is None or y is None:
        from datetime import datetime as _dt
        _n = _dt.now(); m, y = _n.month - 1, _n.year
    return sum(r['mnt'] if r['type'] == 'revenu' else -r['mnt']
               for r in D['rec']
               if r['compte'] == cpt_id
               and r.get('cat') in CATS_NEUTRES
               and rec_active(r, m, y))


# ── v2.4 : Apprentissage borné ────────────────────────────────────────────
# La prévision part du PLAN (récurrentes + cible) puis se corrige doucement
# vers le RÉALISÉ historique, dans des limites strictes :
ALPHA_APPRENTISSAGE = 0.5    # fraction de la correction appliquée (50 %)
CLAMP_CORRECTION    = 0.15   # correction max : ±15 % du plan
MIN_HIST_APPRENT    = 3      # mois d'historique requis pour apprendre


def _hist_avg(hist):
    """Moyenne pondérée récente de l'historique (IQR + poids exponentiels)."""
    if not hist:
        return None
    hist_filt = _iqr_filter(hist)
    if hist_filt:
        w = np.exp(-0.2 * np.arange(len(hist_filt) - 1, -1, -1))
        return float(np.average(hist_filt, weights=w))
    return float(np.median(hist))


def _apprentissage(plan, hist):
    """
    Correction bornée du plan vers le réalisé.
    Retourne (estimation, correction_appliquée, réalisé_moyen).
    Garde-fous : ≥3 mois d'historique, correction plafonnée à ±15 % du plan,
    et seulement 50 % de l'écart appliqué (convergence douce).
    """
    realise = _hist_avg(hist)
    if realise is None or len(hist) < MIN_HIST_APPRENT or plan <= 0:
        return plan, 0.0, realise
    correction = realise - plan
    borne = CLAMP_CORRECTION * plan
    correction = max(-borne, min(borne, correction))
    correction = ALPHA_APPRENTISSAGE * correction
    return plan + correction, correction, realise


def _estimate_rev(D, cpt_id, hist_rev, revenu_cible, m=None, y=None):
    """
    Estime les revenus futurs.
    v2.4 : PLAN (récurrentes + revenu cible) + apprentissage borné vers le
    réalisé historique (hors ⭐, hors neutres, outliers IQR filtrés).
    Si un abonnement/revenu récurrent change sans mise à jour de la
    récurrente, la prévision converge doucement vers la réalité (max ±15 %).
    Sans cible : fallback sur la part variable historique (v2.2).
    """
    if m is None or y is None:
        from datetime import datetime as _dt
        _n = _dt.now(); m, y = _n.month - 1, _n.year
    rec_rev = sum(r['mnt'] for r in D['rec']
                  if r['compte'] == cpt_id and r['type'] == 'revenu'
                  and r.get('cat') not in CATS_NEUTRES
                  and rec_active(r, m, y))

    if revenu_cible > 0:
        plan = rec_rev + revenu_cible
        estimation, _, _ = _apprentissage(plan, hist_rev)
        return estimation

    # Fallback sans cible : part variable historique
    avg_total = _hist_avg(hist_rev)
    avg_var = max(0.0, (avg_total or 0.0) - rec_rev)
    return rec_rev + avg_var


def _estimate_dep(D, cpt_id, hist_dep, budget_cible, m=None, y=None):
    """
    Estime les dépenses futures.
    v2.4 : PLAN (récurrentes + budget cible) + apprentissage borné vers le
    réalisé historique. Si une charge récurrente augmente sans mise à jour
    (abonnement, assurance…), l'écart apparaît dans le réalisé et la
    prévision converge doucement vers la réalité (max ±15 % du plan,
    50 % de l'écart appliqué, ≥3 mois d'historique requis).
    Sans cible : fallback sur la part variable historique (v2.2).
    """
    if m is None or y is None:
        from datetime import datetime as _dt
        _n = _dt.now(); m, y = _n.month - 1, _n.year
    rec_dep = sum(r['mnt'] for r in D['rec']
                  if r['compte'] == cpt_id and r['type'] == 'depense'
                  and r.get('cat') not in CATS_NEUTRES
                  and rec_active(r, m, y))
    if cpt_id == 'ca':
        rec_dep += sum(r['mnt'] for r in D['rec']
                       if r['compte'] == 'mc' and r['type'] == 'depense'
                       and r.get('cat') not in CATS_NEUTRES
                       and rec_active(r, m, y))

    cible_total = sum(budget_cible.values())
    if cible_total > 0:
        plan = rec_dep + cible_total
        estimation, _, _ = _apprentissage(plan, hist_dep)
        return estimation

    # Fallback sans cible : part variable historique
    avg_total = _hist_avg(hist_dep)
    avg_var = max(0.0, (avg_total or 0.0) - rec_dep)
    return rec_dep + avg_var


def detail_estimation(D, cpt_id, n_past=6):
    """
    v2.4 : décomposition complète de l'estimation pour l'affichage
    (panneau Décomposition). Retourne un dict par sens (dep/rev) :
    plan, réalisé moyen, correction appliquée, estimation finale.
    """
    from datetime import datetime as _dt
    now = _dt.now()
    cm, cy = now.month - 1, now.year
    hist_dep = _build_hist_dep(D, cpt_id, cm, cy, n_past)
    hist_rev = _build_hist_rev(D, cpt_id, cm, cy, n_past)

    rec_dep = sum(r['mnt'] for r in D['rec']
                  if r['compte'] == cpt_id and r['type'] == 'depense'
                  and r.get('cat') not in CATS_NEUTRES
                  and rec_active(r, cm, cy))
    if cpt_id == 'ca':
        rec_dep += sum(r['mnt'] for r in D['rec']
                       if r['compte'] == 'mc' and r['type'] == 'depense'
                       and r.get('cat') not in CATS_NEUTRES
                       and rec_active(r, cm, cy))
    rec_rev = sum(r['mnt'] for r in D['rec']
                  if r['compte'] == cpt_id and r['type'] == 'revenu'
                  and r.get('cat') not in CATS_NEUTRES
                  and rec_active(r, cm, cy))

    cible_dep = sum(D.get('budget_cible', {}).get(cpt_id, {}).values())
    cible_rev = float(D.get('revenu_cible', {}).get(cpt_id, 0))

    out = {}
    for sens, rec, cible, hist in [('dep', rec_dep, cible_dep, hist_dep),
                                   ('rev', rec_rev, cible_rev, hist_rev)]:
        plan = rec + cible
        if cible > 0:
            estimation, corr, realise = _apprentissage(plan, hist)
        else:
            realise = _hist_avg(hist)
            estimation = rec + max(0.0, (realise or 0.0) - rec)
            corr = None  # pas d'apprentissage sans cible
        out[sens] = {
            'rec': round(rec, 2), 'cible': round(cible, 2),
            'plan': round(plan, 2),
            'realise': round(realise, 2) if realise is not None else None,
            'correction': round(corr, 2) if corr is not None else None,
            'estimation': round(estimation, 2),
            'n_hist': len(hist),
        }
    return out


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
    Solde foyer = somme des soldes individuels.
    """
    result = []
    for a, b in zip(rows_ca, rows_mb):
        entrees = a['entrees'] + b['entrees']
        sorties = a['sorties'] + b['sorties']
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
