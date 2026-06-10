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
            entrees = _estimate_rev(D, cpt_id, hist_rev, revenu_cible)
            sorties = _estimate_dep(D, cpt_id, hist_dep, budget_cible, m)
            # Récurrentes neutres (virements internes, épargne)
            rec_neutre_rev = sum(r['mnt'] for r in D['rec']
                                 if r['compte'] == cpt_id
                                 and r['type'] == 'revenu'
                                 and r.get('cat') in CATS_NEUTRES)
            rec_neutre_dep = sum(r['mnt'] for r in D['rec']
                                 if r['compte'] == cpt_id
                                 and r['type'] == 'depense'
                                 and r.get('cat') in CATS_NEUTRES)
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


def _rec_neutre_net(D, cpt_id):
    """
    Flux net mensuel des récurrentes NEUTRES (Virement interne, Épargne)
    pour un compte. Exclu des barres d'affichage mais appliqué au solde :
    un virement CA→MB diminue réellement le solde CA et augmente MB.
    """
    return sum(r['mnt'] if r['type'] == 'revenu' else -r['mnt']
               for r in D['rec']
               if r['compte'] == cpt_id
               and r.get('cat') in CATS_NEUTRES)


def _estimate_rev(D, cpt_id, hist_rev, revenu_cible):
    """
    Estime les revenus futurs.
    FIX v2.2 : l'historique (hist_rev) contient DÉJÀ les revenus récurrents
    (saisis comme vraies TX). On soustrait donc rec_rev de la moyenne
    historique pour n'estimer que la part VARIABLE, sinon double comptage
    et prévisionnel gonflé (futur ≈ passé + récurrentes).
    FIX v2.2c : récurrentes NEUTRES (Virement interne, Épargne) exclues
    des barres — cohérent avec le passé (_real_month exclut CATS_NEUTRES).
    """
    rec_rev = sum(r['mnt'] for r in D['rec']
                  if r['compte'] == cpt_id and r['type'] == 'revenu'
                  and r.get('cat') not in CATS_NEUTRES)

    if hist_rev:
        hist_filt = _iqr_filter(hist_rev)
        if hist_filt:
            w = np.exp(-0.2 * np.arange(len(hist_filt) - 1, -1, -1))
            avg_total = float(np.average(hist_filt, weights=w))
        else:
            avg_total = float(np.median(hist_rev))
        # Part variable = total historique − récurrentes (déjà incluses dans les TX)
        avg_var = max(0.0, avg_total - rec_rev)
    else:
        avg_var = 0.0

    # FIX v2.2b : le revenu cible, s'il est renseigné, est la SOURCE PRINCIPALE.
    # L'historique ne sert que de fallback quand aucune cible n'est définie.
    # (Les TX exceptionnelles ⭐ sont déjà exclues de hist_rev, mais celles
    #  non marquées gonflaient l'estimation — la cible évite ce biais.)
    if revenu_cible > 0:
        avg_var = revenu_cible

    return rec_rev + avg_var


def _estimate_dep(D, cpt_id, hist_dep, budget_cible, target_m):
    """
    Estime les dépenses futures.
    FIX v2.2 : même logique que _estimate_rev — l'historique contient déjà
    les dépenses récurrentes, on soustrait rec_dep pour isoler le variable.
    FIX v2.2c : récurrentes NEUTRES (Virement interne, Épargne) exclues
    des barres — cohérent avec le passé (_real_month exclut CATS_NEUTRES).
    """
    rec_dep = sum(r['mnt'] for r in D['rec']
                  if r['compte'] == cpt_id and r['type'] == 'depense'
                  and r.get('cat') not in CATS_NEUTRES)
    if cpt_id == 'ca':
        rec_dep += sum(r['mnt'] for r in D['rec']
                       if r['compte'] == 'mc' and r['type'] == 'depense'
                       and r.get('cat') not in CATS_NEUTRES)

    if hist_dep:
        hist_filt = _iqr_filter(hist_dep)
        if hist_filt:
            w = np.exp(-0.2 * np.arange(len(hist_filt) - 1, -1, -1))
            avg_total = float(np.average(hist_filt, weights=w))
        else:
            avg_total = float(np.median(hist_dep))
        # Part variable = total historique − récurrentes (déjà incluses dans les TX)
        avg_var = max(0.0, avg_total - rec_dep)
    else:
        avg_var = 0.0

    # FIX v2.2b : le budget cible, s'il est renseigné, est la SOURCE PRINCIPALE.
    # L'historique ne sert que de fallback quand aucune cible n'est définie.
    # Prévision = récurrentes + budget cible → cohérent, prévisible, pilotable.
    cible_total = sum(budget_cible.values())
    if cible_total > 0:
        avg_var = cible_total

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
