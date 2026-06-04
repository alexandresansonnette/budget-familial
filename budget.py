"""
Budget Familial AS — Application Streamlit
Stockage : Google Sheets (persistant entre sessions)
Comptes : Crédit Agricole (CA) · Mastercard débit différé (MC) · Monabanq (MB)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
import gspread
import calendar
import numpy as np
from google.oauth2.service_account import Credentials
from datetime import datetime, date
from collections import defaultdict

st.set_page_config(
    page_title="Budget Familial",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Constantes ─────────────────────────────────────────────────────────────────
MOIS = ['Janvier','Février','Mars','Avril','Mai','Juin',
        'Juillet','Août','Septembre','Octobre','Novembre','Décembre']
MOIS_COURT = ['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc']
COMPTES = {
    'ca': {'label':'Crédit Agricole','color':'#378ADD','bg':'#E6F1FB','tc':'#0C447C'},
    'mc': {'label':'Mastercard',     'color':'#BA7517','bg':'#FAEEDA','tc':'#633806'},
    'mb': {'label':'Monabanq',       'color':'#1D9E75','bg':'#E1F5EE','tc':'#085041'},
}
CATS_DEFAULT = sorted([
    'ARE / Salaire','Allocations','Revenu freelance','Prêt / Assurance',
    'Frais divers','Nourriture','Habit / Beauté','Santé','Sénégal',
    'CLAE / École','Loisirs / Vacances','Voiture','Abonnement','Tontine',
    'Épargne','Virement interne','Impôts / Taxes','Divers'
])
# Catégories neutres : exclues du prévisionnel côté revenus ET dépenses
# car elles représentent des flux internes sans impact sur le solde global
CATS_NEUTRES = {'Virement interne', 'Épargne'}
CC = ['#378ADD','#1D9E75','#D85A30','#D4537E','#7F77DD',
      '#639922','#BA7517','#E24B4A','#888780','#0F6E56']
GSHEET_NAME = "Budget Familial AS"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets',
          'https://www.googleapis.com/auth/drive']

# ── Helpers format ──────────────────────────────────────────────────────────────
def fmt(n):
    if n is None: return "—"
    return f"{n:,.0f} €".replace(",", "\u202f")

def fmt2(n):
    if n is None: return "—"
    return f"{n:,.2f} €".replace(",", "\u202f")

def aff_key(t):
    if t.get('compte') == 'mc' and t.get('affM') is not None and t.get('affY') is not None:
        return (int(t['affY']), int(t['affM']))
    d = datetime.strptime(t['date'], '%Y-%m-%d')
    return (d.year, d.month - 1)

def month_add(m, y, n):
    total = y * 12 + m + n
    return total % 12, total // 12

# ── Google Sheets ───────────────────────────────────────────────────────────────
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
            return json.loads(payload)
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

        # Écrire dans un onglet tampon d'abord (évite la perte si clear() plante)
        try:
            ws_tmp = sh.worksheet("data_tmp")
            ws_tmp.clear()
        except gspread.WorksheetNotFound:
            ws_tmp = sh.add_worksheet(title="data_tmp", rows=2000, cols=2)
        ws_tmp.update(
            range_name=f"A1:A{len(chunks)}",
            values=[[chunk] for chunk in chunks]
        )

        # Lecture de contrôle : vérifier que le tampon est lisible et cohérent
        readback = "".join(ws_tmp.col_values(1))
        data_check = json.loads(readback)
        if len(data_check.get('tx', [])) != len(data.get('tx', [])):
            raise ValueError(f"Contrôle échoué : {len(data_check.get('tx',[]))} TX relues vs {len(data.get('tx',[]))} attendues")

        # Tout est OK → écrire dans l'onglet principal
        ws.clear()
        ws.update(
            range_name=f"A1:A{len(chunks)}",
            values=[[chunk] for chunk in chunks]
        )

        # Stocker timestamp dernière sauvegarde réussie
        st.session_state['last_save_ok'] = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    except Exception as e:
        st.error(f"❌ Erreur de sauvegarde : {e}")
        st.warning("⚠️ Les données n'ont PAS été sauvegardées. Exportez un JSON de secours immédiatement.")

# ── Session state ───────────────────────────────────────────────────────────────
if 'data' not in st.session_state:
    st.session_state.data = load_from_gsheet()
if 'cur_m' not in st.session_state:
    st.session_state.cur_m = datetime.now().month - 1
if 'cur_y' not in st.session_state:
    st.session_state.cur_y = datetime.now().year
if 'fcpt' not in st.session_state:
    st.session_state.fcpt = 'all'
if 'last_saisie_cpt' not in st.session_state:
    st.session_state.last_saisie_cpt = 'ca'

D = st.session_state.data

if D['cats'] and isinstance(D['cats'][0], str):
    D['cats'] = [{'nom': c, 'visible': True} for c in D['cats']]

def persist():
    save_to_gsheet(st.session_state.data)

def visible_cats():
    return sorted([c['nom'] for c in D['cats'] if c.get('visible', True)])

def all_cats():
    return sorted([c['nom'] for c in D['cats']])

# ── Calculs ─────────────────────────────────────────────────────────────────────
def tx_of_month(m, y, tx=None):
    if tx is None: tx = D['tx']
    return [t for t in tx if aff_key(t) == (y, m)]

def rec_applied(rid, m, y):
    return any(t.get('recId') == rid and aff_key(t) == (y, m) for t in D['tx'])

def get_sol(c, m, y):
    v = D['sol'].get(f"{c}_{y}_{m}")
    return float(v) if v is not None else None

def set_sol(c, m, y, v):
    k = f"{c}_{y}_{m}"
    if v is not None: D['sol'][k] = v
    else: D['sol'].pop(k, None)

def solde_a_date(cpt_id):
    now = datetime.now()
    m, y = now.month - 1, now.year
    deb = get_sol(cpt_id, m, y)
    if deb is None: return None
    txs = [t for t in D['tx'] if t['compte'] == cpt_id
           and aff_key(t) == (y, m)
           and datetime.strptime(t['date'], '%Y-%m-%d') <= now]
    return deb + sum(t['montant'] if t['type']=='revenu' else -t['montant'] for t in txs)

def upcoming_rec(cpt_id):
    now = datetime.now()
    m, y = now.month - 1, now.year
    return sorted(
        [r for r in D['rec'] if r['compte'] == cpt_id
         and r['jour'] > now.day and not rec_applied(r['id'], m, y)],
        key=lambda r: r['jour']
    )

def get_alerts(cpt_id):
    od = D['overdraft'].get(cpt_id, 0)
    solde = solde_a_date(cpt_id)
    if solde is None: return []
    alerts = []
    if solde < -od:
        alerts.append(('danger', f"Solde dans le rouge : {fmt2(solde)}"))
    elif solde < (-od + 300):
        alerts.append(('warn', f"Solde proche de la limite : {fmt2(solde)}"))
    proj = solde
    for r in upcoming_rec(cpt_id):
        prev = proj
        proj += r['mnt'] if r['type'] == 'revenu' else -r['mnt']
        if proj < -od and prev >= -od:
            alerts.append(('warn', f"« {r['nom']} » ({fmt2(r['mnt'])}) le {r['jour']} → {fmt2(proj)}"))
    return alerts

def month_net(cpt_id, m, y, forecast=False):
    if not forecast:
        return sum(t['montant'] if t['type']=='revenu' else -t['montant']
                   for t in tx_of_month(m, y) if t['compte'] == cpt_id)
    rec_n = sum(r['mnt'] if r['type']=='revenu' else -r['mnt']
                for r in D['rec'] if r['compte'] == cpt_id)
    past = []
    now = datetime.now()
    cm, cy = now.month - 1, now.year
    for i in range(1, 7):
        pm, py = month_add(cm, cy, -i)
        txs = [t for t in tx_of_month(pm, py) if t['compte'] == cpt_id and not t.get('recId')]
        if txs:
            past.append(sum(t['montant'] if t['type']=='revenu' else -t['montant'] for t in txs))
    return rec_n + (sum(past)/len(past) if past else 0)

# ── Fonctions centralisées Mastercard ───────────────────────────────────────
# Source unique de vérité pour tous les calculs MC → zéro double comptage

def mc_depenses_reelles(m, y, jusqu_au=None):
    """
    Total des dépenses MC affectées au mois (m, y) 0-indexed.
    jusqu_au : datetime optionnel — ne prend que les TX dont date réelle <= jusqu_au.
    Utilisé pour : encours à date, solde mensuel CA, prévisionnel, trésorerie.
    """
    txs = [t for t in D['tx']
           if t['compte'] == 'mc'
           and t['type'] == 'depense'
           and aff_key(t) == (y, m)]
    if jusqu_au is not None:
        txs = [t for t in txs
               if datetime.strptime(t['date'], '%Y-%m-%d') <= jusqu_au]
    return sum(t['montant'] for t in txs)

def mc_rec_depenses():
    """Total mensuel des récurrentes MC dépenses (montant fixe prévisible)."""
    return sum(r['mnt'] for r in D['rec']
               if r['compte'] == 'mc' and r['type'] == 'depense')

def mc_rec_non_appliquees(m, y):
    """Récurrentes MC dépenses pas encore appliquées au mois (m, y) 0-indexed."""
    return sum(r['mnt'] for r in D['rec']
               if r['compte'] == 'mc' and r['type'] == 'depense'
               and not rec_applied(r['id'], m, y))

# ── Prévisionnel refondu ────────────────────────────────────────────────────────
def resolve_sol(cpt_id, target_m, target_y):
    """
    Retourne (solde_debut_mois, source) pour (target_m, target_y).
    Cherche le solde saisi le plus proche (passé en priorité, sinon futur),
    puis propage mois par mois jusqu'à la cible.
    source = 'saisi' | 'calculé' | None
    """
    # 1. Solde direct ?
    v = get_sol(cpt_id, target_m, target_y)
    if v is not None:
        return v, 'saisi'

    target_abs = target_y * 12 + target_m

    # 2. Chercher tous les soldes saisis dans D['sol'] pour ce compte
    candidates = []
    for key, val in D['sol'].items():
        parts = key.split('_')
        if len(parts) == 3 and parts[0] == cpt_id:
            try:
                ky, km = int(parts[1]), int(parts[2])
                candidates.append((ky * 12 + km, km, ky, float(val)))
            except ValueError:
                pass

    if not candidates:
        return None, None

    # 3. Trouver le candidat le plus proche (passé en priorité)
    past = [(abs_m, mm, yy, val) for abs_m, mm, yy, val in candidates if abs_m <= target_abs]
    future = [(abs_m, mm, yy, val) for abs_m, mm, yy, val in candidates if abs_m > target_abs]

    if past:
        src_abs, src_m, src_y, src_val = max(past, key=lambda x: x[0])
    elif future:
        src_abs, src_m, src_y, src_val = min(future, key=lambda x: x[0])
    else:
        return None, None

    # 4. Propager de src vers target mois par mois
    sol = src_val
    step = 1 if src_abs <= target_abs else -1
    cur_abs = src_abs
    while cur_abs != target_abs:
        if step == 1:
            # On avance : appliquer les mouvements du mois courant pour obtenir début mois suivant
            cur_m, cur_y = cur_abs % 12, cur_abs // 12
            mvt = sum(t['montant'] if t['type'] == 'revenu' else -t['montant']
                      for t in D['tx'] if t['compte'] == cpt_id and aff_key(t) == (cur_y, cur_m))
            if cpt_id == 'ca':
                mvt -= mc_depenses_reelles(cur_m, cur_y)
            sol += mvt
        else:
            # On recule : soustraire les mouvements du mois précédent
            prev_abs = cur_abs - 1
            prev_m, prev_y = prev_abs % 12, prev_abs // 12
            mvt = sum(t['montant'] if t['type'] == 'revenu' else -t['montant']
                      for t in D['tx'] if t['compte'] == cpt_id and aff_key(t) == (prev_y, prev_m))
            if cpt_id == 'ca':
                mvt -= mc_depenses_reelles(prev_m, prev_y)
            sol -= mvt
        cur_abs += step

    return sol, 'calculé'


def prevision_depenses(cpt_id, mois_cibles):
    """
    Prévision des dépenses variables par catégorie.
    - Exclut : virements internes, catégories récurrentes connues
    - Filtre IQR : exclut les valeurs aberrantes (outliers) par catégorie
    - Modèle combiné : EWM + tendance linéaire + saisonnalité
    - MC : incluse dans l'historique CA mais PAS dans rec_total (évite double comptage)
    """
    now = datetime.now()
    cm, cy = now.month - 1, now.year

    # Catégories à exclure du variable (ne reflètent pas une vraie dépense nette)
    CATS_EXCLUES = CATS_NEUTRES

    # Récurrentes connues : leurs catégories sont fixes → exclues du variable
    rec_ids = {r['id'] for r in D['rec']}

    # Historique mensuel variable par catégorie (18 mois max)
    hist_months = [month_add(cm, cy, -i) for i in range(1, 19)]
    hist_months.reverse()

    hist = defaultdict(list)
    for m, y in hist_months:
        abs_m = y * 12 + m
        # TX directes du compte (hors récurrentes, hors catégories exclues)
        tx_m = [t for t in D['tx']
                if t['compte'] == cpt_id
                and aff_key(t) == (y, m)
                and t['type'] == 'depense'
                and not t.get('recId')
                and not t.get('exceptionnel', False)
                and t.get('categorie') not in CATS_EXCLUES]
        # Pour CA : inclure TX MC non-récurrentes affectées à ce mois
        if cpt_id == 'ca':
            tx_m += [t for t in D['tx']
                     if t['compte'] == 'mc'
                     and t['type'] == 'depense'
                     and not t.get('recId')
                     and not t.get('exceptionnel', False)
                     and t.get('categorie') not in CATS_EXCLUES
                     and aff_key(t) == (y, m)]
        cat_totals = defaultdict(float)
        for t in tx_m:
            cat_totals[t['categorie']] += t['montant']
        for cat, total in cat_totals.items():
            hist[cat].append((abs_m, total))

    # Filtre IQR par catégorie : exclure les mois aberrants (outliers)
    def filter_iqr(data):
        if len(data) < 4:
            return data
        vals = np.array([v for _, v in data])
        q1, q3 = np.percentile(vals, 25), np.percentile(vals, 75)
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        return [(a, v) for a, v in data if lo <= v <= hi]

    def predict_cat(cat, target_m, target_y):
        raw = sorted(hist.get(cat, []), key=lambda x: x[0])
        data = filter_iqr(raw)
        n = len(data)
        if n == 0:
            # Si tout a été filtré, prendre la médiane brute
            if raw:
                return float(np.median([v for _, v in raw])), 0.0, float(np.median([v for _, v in raw]))
            return 0.0, 0.0, 0.0

        vals = np.array([v for _, v in data])
        abs_months = np.array([a for a, _ in data])
        target_abs = target_y * 12 + target_m

        # Composante 1 : EWM
        decay = 0.25
        weights = np.exp(-decay * (target_abs - abs_months))
        weights = np.maximum(weights, 1e-6)
        ewm = float(np.average(vals, weights=weights))

        # Composante 2 : tendance linéaire (si n >= 3)
        if n >= 3:
            x = abs_months - abs_months.mean()
            x_target = target_abs - abs_months.mean()
            trend_val = max(0.0, float(np.polyval(np.polyfit(x, vals, 1), x_target)))
            w_trend = min(0.4, (n - 2) / 8 * 0.4)
        else:
            trend_val = ewm
            w_trend = 0.0

        # Composante 3 : saisonnalité (si >= 2 obs du même mois)
        same_month = [(a, v) for a, v in data if a % 12 == target_m]
        if len(same_month) >= 2:
            overall_mean = vals.mean() if vals.mean() > 0 else 1.0
            seasonal_ratio = np.mean([v for _, v in same_month]) / overall_mean
            w_seasonal = min(0.3, len(same_month) / 4 * 0.3)
        else:
            seasonal_ratio = 1.0
            w_seasonal = 0.0

        w_ewm = 1.0 - w_trend - w_seasonal
        if w_seasonal > 0:
            pred = w_ewm * ewm + w_trend * trend_val + w_seasonal * (ewm * seasonal_ratio)
        else:
            pred = w_ewm * ewm + w_trend * trend_val
        pred = max(0.0, pred)

        # Intervalle de confiance
        if n >= 2:
            std = float(np.std(vals))
            ic_factor = min(1.28, 0.5 + n * 0.1)
            margin = std * ic_factor
        else:
            margin = pred * 0.3
        return pred, max(0.0, pred - margin), pred + margin

    # Récurrentes DEPENSES fixes (sans MC pour CA → déjà dans hist variable)
    rec_total_ca_propre = sum(r['mnt'] for r in D['rec']
                              if r['compte'] == cpt_id and r['type'] == 'depense')
    # MC récurrentes ajoutées séparément pour CA (débit différé fixe)
    mc_rec_total = mc_rec_depenses() if cpt_id == 'ca' else 0.0

    results = []
    for target_m, target_y in mois_cibles:
        par_cat = {}
        for cat in sorted(hist.keys()):
            moyen, lo, hi = predict_cat(cat, target_m, target_y)
            data = filter_iqr(sorted(hist.get(cat, []), key=lambda x: x[0]))
            if len(data) >= 3:
                recent = np.mean([v for _, v in data[-3:]])
                older  = np.mean([v for _, v in data[:max(1, len(data)-3)]])
                tendance = "hausse" if recent > older*1.1 else ("baisse" if recent < older*0.9 else "stable")
            else:
                tendance = "insuffisant"
            par_cat[cat] = {'moyen': moyen, 'min': lo, 'max': hi, 'tendance': tendance}

        var_moyen = sum(v['moyen'] for v in par_cat.values())
        var_min   = sum(v['min']   for v in par_cat.values())
        var_max   = sum(v['max']   for v in par_cat.values())
        rec_total = rec_total_ca_propre + mc_rec_total

        results.append({
            'variable_moyen': var_moyen,
            'variable_min':   var_min,
            'variable_max':   var_max,
            'recurrentes':    rec_total,
            'total_moyen':    var_moyen + rec_total,
            'total_min':      var_min   + rec_total,
            'total_max':      var_max   + rec_total,
            'par_categorie':  par_cat
        })
    return results


def build_forecast_v2():
    """
    Prévisionnel refondu.

    Passé (-6 mois à aujourd'hui) :
      - Courbe jour par jour (1 point / jour calendaire)
      - CA & MB : TX réelles du compte cumulées depuis solde début
      - MC : cumul mensuel soustrait le DERNIER jour du mois d'affectation sur CA uniquement

    Mois courant :
      - Réel jusqu'à aujourd'hui + récurrentes restantes projetées

    Futur (+1 à +5 mois) :
      - 1 point par mois = solde fin estimé
      - base = solde fin mois précédent + rec_net + moyenne TX non-rec passées - MC rec (CA)

    Retourne :
      months         : liste (m, y) 0-indexed, 12 éléments
      daily_series   : { 'ca': [(date_str, solde), ...], 'mb': [...] }
      monthly_series : { 'ca': [(label, valeur, is_forecast), ...], 'mb': [...] }
      warnings       : [str, ...]
    """
    now = datetime.now()
    cm, cy = now.month - 1, now.year

    months = [month_add(cm, cy, i) for i in range(-6, 6)]
    warnings_out = []
    daily_series = {'ca': [], 'mb': []}
    monthly_series = {'ca': [], 'mb': []}

    for cpt_id in ['ca', 'mb']:
        # Solde de départ : début du mois le plus ancien (-6)
        start_m, start_y = months[0]
        base_sol, src = resolve_sol(cpt_id, start_m, start_y)  # noqa
        if base_sol is None:
            warnings_out.append(
                f"⚠️ Aucun solde historique trouvé pour **{COMPTES[cpt_id]['label']}** "
                f"— courbe calculée depuis 0 €."
            )
            base_sol = 0.0

        # ── Courbe journalière : mois -6 à mois courant ────────────────────
        daily_pts = []
        sol_running = base_sol

        for idx in range(7):  # indices 0 (mois-6) à 6 (mois courant)
            m, y = months[idx]
            is_current = (idx == 6)
            last_day = calendar.monthrange(y, m + 1)[1]

            # TX directes du compte sur ce mois (date réelle pour CA/MB)
            tx_direct = [
                t for t in D['tx']
                if t['compte'] == cpt_id
                and datetime.strptime(t['date'], '%Y-%m-%d').year == y
                and datetime.strptime(t['date'], '%Y-%m-%d').month == m + 1
            ]

            # Cumul MC affecté à ce mois (soustrait le dernier jour sur CA)
            mc_cumul = 0.0
            mc_cumul = mc_depenses_reelles(m, y) if cpt_id == 'ca' else 0.0

            # Deltas par jour
            daily_delta = defaultdict(float)
            for t in tx_direct:
                d_obj = datetime.strptime(t['date'], '%Y-%m-%d')
                delta = t['montant'] if t['type'] == 'revenu' else -t['montant']
                daily_delta[d_obj.day] += delta

            # Mois courant : projeter récurrentes non encore appliquées
            if is_current:
                for r in D['rec']:
                    if r['compte'] == cpt_id and r['jour'] > now.day and not rec_applied(r['id'], m, y):
                        delta = r['mnt'] if r['type'] == 'revenu' else -r['mnt']
                        daily_delta[r['jour']] += delta
                if cpt_id == 'ca':
                    mc_cumul += mc_rec_non_appliquees(m, y)

            # Construire point par jour
            sol_day = sol_running
            for day in range(1, last_day + 1):
                sol_day += daily_delta.get(day, 0.0)
                if day == last_day and mc_cumul > 0 and cpt_id == 'ca':
                    sol_day -= mc_cumul
                day_str = f"{y}-{m+1:02d}-{day:02d}"
                daily_pts.append((day_str, round(sol_day, 2)))

            sol_running = sol_day  # fin de mois = départ mois suivant

        daily_series[cpt_id] = daily_pts

        # ── Points mensuels (12 mois) ──────────────────────────────────────
        # Revenus futurs = récurrentes revenus + moyenne pondérée revenus passés non-récurrents
        rec_rev = sum(r['mnt'] for r in D['rec']
                      if r['compte'] == cpt_id and r['type'] == 'revenu')

        past_rev_nets = []
        for i in range(6):  # 6 mois passés
            pm2, py2 = months[i]
            tx_rev = [t for t in D['tx']
                      if t['compte'] == cpt_id
                      and aff_key(t) == (py2, pm2)
                      and t['type'] == 'revenu'
                      and not t.get('recId')
                      and not t.get('exceptionnel', False)
                      and t.get('categorie') not in CATS_NEUTRES]
            if tx_rev:
                past_rev_nets.append(sum(t['montant'] for t in tx_rev))
        # Filtre IQR sur les revenus variables pour éliminer les mois atypiques
        if len(past_rev_nets) >= 4:
            q1_r, q3_r = np.percentile(past_rev_nets, 25), np.percentile(past_rev_nets, 75)
            iqr_r = q3_r - q1_r
            past_rev_nets = [v for v in past_rev_nets
                             if q1_r - 1.5*iqr_r <= v <= q3_r + 1.5*iqr_r]
        # EWM sur les revenus variables filtrés
        if past_rev_nets:
            w = np.exp(-0.2 * np.arange(len(past_rev_nets)-1, -1, -1))
            avg_rev_var = float(np.average(past_rev_nets, weights=w))
        else:
            avg_rev_var = 0.0

        rev_futur = rec_rev + avg_rev_var

        # Prévision dépenses par catégorie (modèle combiné + IQR)
        future_months = [(m, y) for m, y in months[7:]]  # mois +1 à +5
        fc_results = prevision_depenses(cpt_id, future_months) if future_months else []

        monthly_pts = []
        fc_idx = 0
        for idx in range(12):
            m, y = months[idx]
            rel = idx - 6
            label = f"{MOIS_COURT[m]} {y}"

            if rel <= 0:
                # Passé + mois courant : solde fin de mois depuis courbe journalière
                prefix = f"{y}-{m+1:02d}-"
                pts_m = [(ds, sv) for ds, sv in daily_series[cpt_id] if ds.startswith(prefix)]
                val = pts_m[-1][1] if pts_m else None
                val_min = val_max = val
                is_fc = False
            else:
                # Futur : solde précédent + revenus estimés - dépenses estimées
                prev_val = monthly_pts[-1][0] if monthly_pts else None
                if prev_val is None:
                    val = val_min = val_max = None
                else:
                    fc = fc_results[fc_idx] if fc_idx < len(fc_results) else None
                    if fc:
                        dep_moyen = fc['total_moyen']
                        dep_min   = fc['total_min']
                        dep_max   = fc['total_max']
                    else:
                        dep_moyen = dep_min = dep_max = 0.0
                    val     = prev_val + rev_futur - dep_moyen
                    val_min = prev_val + rev_futur - dep_max   # pire cas : sorties max
                    val_max = prev_val + rev_futur - dep_min   # meilleur cas : sorties min
                fc_idx += 1
                is_fc = True

            monthly_pts.append((val, val_min, val_max, label, is_fc))

        monthly_series[cpt_id] = monthly_pts

        monthly_series[cpt_id] = monthly_pts

    return months, daily_series, monthly_series, warnings_out


def projection_fin_mois(cpt_id):
    """
    Rejoue toutes les TX du mois depuis le solde de début de mois,
    puis projette les événements futurs restants.

    Stratégie :
      - Partir du solde saisi au 1er du mois (ou calculé via resolve_sol)
      - Rejouer TOUTES les TX réelles du mois jusqu'à aujourd'hui (passé réel)
      - Projeter les événements futurs :
          * TX déjà saisies avec date future (hors récurrentes MC)
          * Récurrentes non encore appliquées
          * Prélèvement MC total en fin de mois
      - La courbe montre ainsi le passé réel + le futur projeté
    """
    now = datetime.now()
    m, y = now.month - 1, now.year
    last_day = calendar.monthrange(y, m + 1)[1]
    od = D['overdraft'].get(cpt_id, 0)
    limite = -od

    # Solde de début de mois
    sol_debut, _ = resolve_sol(cpt_id, m, y)
    if sol_debut is None:
        return {'solde_actuel': None, 'jours': [], 'solde_fin': None,
                'point_bas': (None, None), 'point_bas_jour': None,
                'manque': 0, 'statut': 'ok', 'od': od, 'marge': None}

    # Solde actuel calculé (pour l'affichage dans le bandeau)
    solde_act = solde_a_date(cpt_id)

    # ── Construire les deltas jour par jour pour tout le mois ─────────────
    daily_events = defaultdict(list)   # jour → [(nom, delta, is_future)]

    # 1. TX réelles déjà saisies (passé ET futur avec date dans ce mois)
    for t in D['tx']:
        if t['compte'] != cpt_id: continue
        if aff_key(t) != (y, m): continue
        t_date = datetime.strptime(t['date'], '%Y-%m-%d')
        delta = t['montant'] if t['type'] == 'revenu' else -t['montant']
        nom = t.get('note') or t['categorie']
        is_future = t_date.date() > now.date()
        daily_events[t_date.day].append((nom, delta, is_future))

    # 2. Récurrentes NON encore appliquées (pas encore dans D['tx'])
    for r in D['rec']:
        if r['compte'] == cpt_id and not rec_applied(r['id'], m, y):
            delta = r['mnt'] if r['type'] == 'revenu' else -r['mnt']
            daily_events[r['jour']].append((r['nom'], delta, True))

    # 3. Prélèvement MC total sur CA en fin de mois
    if cpt_id == 'ca':
        mc_total  = mc_depenses_reelles(m, y)
        mc_rec_r  = mc_rec_non_appliquees(m, y)
        mc_prelev = mc_total + mc_rec_r
        if mc_prelev > 0:
            daily_events[last_day].append(('Prélèvement MC', -mc_prelev, True))

    # ── Rejouer jour par jour depuis le solde début ────────────────────────
    sol = sol_debut
    jours = []
    point_bas_sol = sol_debut
    point_bas_jour = 1

    for day in range(1, last_day + 1):
        evts = daily_events.get(day, [])
        for nom, delta, _ in evts:
            sol += delta
        date_str = f"{day:02d}/{m+1:02d}"
        # Événements visibles dans la liste = futurs uniquement (utiles pour l'utilisateur)
        evts_affich = [(n, d) for n, d, fut in evts if fut]
        jours.append((date_str, round(sol, 2), evts_affich))
        if sol < point_bas_sol:
            point_bas_sol = sol
            point_bas_jour = day

    sol_fin = jours[-1][1] if jours else sol_debut
    marge   = sol_fin - limite
    manque  = max(0.0, -(min(point_bas_sol, sol_fin) - limite))

    if point_bas_sol < limite:
        statut = 'danger'
    elif point_bas_sol < limite + 300:
        statut = 'warn'
    else:
        statut = 'ok'

    return {
        'solde_actuel': solde_act,
        'jours':        jours,
        'solde_fin':    sol_fin,
        'point_bas':    (f"{point_bas_jour:02d}/{m+1:02d}", round(point_bas_sol, 2)),
        'point_bas_jour': point_bas_jour,
        'manque':       round(manque, 2),
        'statut':       statut,
        'od':           od,
        'marge':        round(marge, 2),
        'limite':       limite,
        'sol_debut':    sol_debut,
    }

st.markdown("""
<style>
.main > div { padding-top: 1rem; }
.metric-card { border: 1px solid #e0e0e0; border-radius: 10px; padding: 14px 16px; margin-bottom: 8px; }
.today-ok     { border-left: 4px solid #1D9E75; }
.today-warn   { border-left: 4px solid #D97706; }
.today-danger { border-left: 4px solid #E24B4A; }
.alert-danger { background:#fdf0f0; border-left:4px solid #E24B4A; padding:10px 14px; border-radius:6px; margin-bottom:8px; color:#791F1F; font-size:13px; }
.alert-warn   { background:#fff8e6; border-left:4px solid #D97706; padding:10px 14px; border-radius:6px; margin-bottom:8px; color:#7C4A00; font-size:13px; }
.alert-ok     { background:#f0faf4; border-left:4px solid #1D9E75; padding:10px 14px; border-radius:6px; margin-bottom:8px; color:#085041; font-size:13px; }
</style>
""", unsafe_allow_html=True)

# ── NAVIGATION ──────────────────────────────────────────────────────────────────
nc1, nc2, nc3, nc4, nc5 = st.columns([1, 2, 1, 2, 2])
with nc1:
    if st.button("◀", width="stretch"):
        if st.session_state.cur_m == 0: st.session_state.cur_m = 11; st.session_state.cur_y -= 1
        else: st.session_state.cur_m -= 1
        st.rerun()
with nc2:
    nm = st.selectbox("Mois", range(12), index=st.session_state.cur_m,
                      format_func=lambda x: MOIS[x], label_visibility='collapsed')
    if nm != st.session_state.cur_m: st.session_state.cur_m = nm; st.rerun()
with nc3:
    if st.button("▶", width="stretch"):
        if st.session_state.cur_m == 11: st.session_state.cur_m = 0; st.session_state.cur_y += 1
        else: st.session_state.cur_m += 1
        st.rerun()
with nc4:
    ny = st.selectbox("Année", range(2023, 2031), index=list(range(2023,2031)).index(st.session_state.cur_y),
                      label_visibility='collapsed')
    if ny != st.session_state.cur_y: st.session_state.cur_y = ny; st.rerun()
with nc5:
    fopts = {'all':'Tous les comptes', **{k: v['label'] for k,v in COMPTES.items()}}
    nf = st.selectbox("Compte", list(fopts.keys()), format_func=lambda x: fopts[x], label_visibility='collapsed')
    if nf != st.session_state.fcpt: st.session_state.fcpt = nf; st.rerun()

M, Y, FCPT = st.session_state.cur_m, st.session_state.cur_y, st.session_state.fcpt
TX_CUR = [t for t in tx_of_month(M, Y) if FCPT == 'all' or t['compte'] == FCPT]

st.divider()

tabs = st.tabs(["📍 Aujourd'hui","📊 Mois","📋 Transactions","✏️ Saisie",
                "🔄 Récurrentes","📈 Prévisionnel","🏦 Prêts","🏷️ Catégories","🔬 Diagnostic","💾 Sauvegarde"])

# ══════════════════════════════════════════════════════════════════════════════
# AUJOURD'HUI
# ══════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    now = datetime.now()
    m_now, y_now = now.month - 1, now.year
    last_day_now = calendar.monthrange(y_now, m_now + 1)[1]

    # ── Projections des deux comptes ───────────────────────────────────────
    proj_ca = projection_fin_mois('ca')
    proj_mb = projection_fin_mois('mb')

    # ── Sélecteur de compte pour le cockpit ────────────────────────────────
    st.markdown(f"#### Cockpit trésorerie — {now.strftime('%d/%m/%Y')}")
    cpt_cockpit = st.radio("Compte affiché", ['ca', 'mb'],
                           format_func=lambda x: COMPTES[x]['label'],
                           horizontal=True, key="cockpit_cpt")
    proj = proj_ca if cpt_cockpit == 'ca' else proj_mb
    cpt_info = COMPTES[cpt_cockpit]

    # ══ 1. BANDEAU SYNTHÈSE ════════════════════════════════════════════════
    if proj['solde_actuel'] is None:
        st.warning(f"⚠️ Solde de début de mois non renseigné pour {cpt_info['label']} — allez dans l'onglet Mois pour le saisir.")
    else:
        statut = proj['statut']
        sol_fin = proj['solde_fin']
        pb_date, pb_sol = proj['point_bas']
        marge = proj['marge']
        od = proj['od']
        limite = proj['limite']

        if statut == 'ok':
            emoji, titre, bg, border = "🟢", "Fin de mois sécurisée", "#f0faf4", "#1D9E75"
        elif statut == 'warn':
            emoji, titre, bg, border = "🟠", "Vigilance", "#fff8e6", "#D97706"
        else:
            emoji, titre, bg, border = "🔴", "Risque de découvert", "#fdf0f0", "#E24B4A"

        # Construire les blocs HTML optionnels proprement (pas d'apostrophes imbriquées)
        sol_color = "#E24B4A" if (sol_fin or 0) < 0 else "#1D9E75"
        marge_bloc = ""
        if statut == 'ok':
            marge_bloc = f'<div style="font-size:13px;color:#1D9E75;margin-top:4px;">Marge avant découvert : {fmt2(marge)}</div>'
        od_bloc = ""
        if od > 0:
            od_bloc = f'<div style="font-size:12px;color:#888;margin-top:4px;">Découvert autorisé : {fmt2(limite)}</div>'
        manque_bloc = ""
        if proj['manque'] > 0:
            manque_bloc = f'<div style="font-size:14px;font-weight:600;color:#E24B4A;margin-top:6px;">Manque estimé : {fmt2(proj["manque"])}</div>'

        html_bandeau = (
            f'<div style="background:{bg};border-left:5px solid {border};'
            f'border-radius:10px;padding:16px 20px;margin-bottom:16px;">'
            f'<div style="font-size:18px;font-weight:700;margin-bottom:8px;">{emoji} {titre}</div>'
            f'<div style="font-size:15px;">Solde estimé au {last_day_now:02d}/{m_now+1:02d} : '
            f'<strong style="color:{sol_color}">{fmt2(sol_fin)}</strong></div>'
            f'<div style="font-size:13px;color:#555;margin-top:4px;">'
            f'Point le plus bas : <strong>{fmt2(pb_sol)}</strong> le {pb_date}</div>'
            f'{marge_bloc}{od_bloc}{manque_bloc}'
            f'</div>'
        )
        st.markdown(html_bandeau, unsafe_allow_html=True)

        # ══ 2. COURBE TRÉSORERIE JUSQU'À FIN DE MOIS ══════════════════════
        if proj['jours']:
            color = cpt_info['color']
            r_int = int(color[1:3], 16)
            g_int = int(color[3:5], 16)
            b_int = int(color[5:7], 16)

            # Courbe complète : passé (01 → aujourd'hui) + futur (aujourd'hui → fin mois)
            x_vals = [j[0] for j in proj['jours']]
            y_vals = [j[1] for j in proj['jours']]
            today_str = f"{now.day:02d}/{m_now+1:02d}"

            # Séparer passé et futur pour colorer différemment
            x_past = [j[0] for j in proj['jours'] if int(j[0][:2]) <= now.day]
            y_past = [j[1] for j in proj['jours'] if int(j[0][:2]) <= now.day]
            x_futur = [j[0] for j in proj['jours'] if int(j[0][:2]) >= now.day]
            y_futur = [j[1] for j in proj['jours'] if int(j[0][:2]) >= now.day]

            # Identifier les jours futurs avec événements
            evt_x, evt_y, evt_txt = [], [], []
            for date_s, sol_j, evts in proj['jours']:
                if evts and int(date_s[:2]) > now.day:
                    evt_x.append(date_s)
                    evt_y.append(sol_j)
                    lines_evt = "<br>".join(
                        f"{'▲' if d>0 else '▼'} {n} : {'+' if d>0 else ''}{fmt2(d)}"
                        for n, d in evts
                    )
                    evt_txt.append(lines_evt)

            fig_c = go.Figure()

            # Zone sous 0
            all_y = [v for v in y_vals if v is not None]
            fig_c.add_hrect(
                y0=min(min(all_y)*1.15 if all_y else -500, limite*1.3), y1=0,
                fillcolor="rgba(220,50,50,0.05)", line_width=0
            )

            # Courbe passé (pleine)
            if x_past:
                fig_c.add_trace(go.Scatter(
                    x=x_past, y=y_past,
                    mode='lines',
                    name=f"{cpt_info['label']} (réel)",
                    line=dict(color=color, width=2.5),
                    fill='tozeroy',
                    fillcolor=f"rgba({r_int},{g_int},{b_int},0.10)",
                    hovertemplate='%{x}<br>Solde réel : %{y:,.2f} €<extra></extra>'
                ))

            # Courbe futur (pointillé)
            if x_futur:
                fig_c.add_trace(go.Scatter(
                    x=x_futur, y=y_futur,
                    mode='lines',
                    name=f"{cpt_info['label']} (estimé)",
                    line=dict(color=color, width=2, dash='dot'),
                    fill='tozeroy',
                    fillcolor=f"rgba({r_int},{g_int},{b_int},0.04)",
                    hovertemplate='%{x}<br>Solde estimé : %{y:,.2f} €<extra></extra>'
                ))

            # Marqueurs événements
            if evt_x:
                fig_c.add_trace(go.Scatter(
                    x=evt_x, y=evt_y,
                    mode='markers',
                    name='Événements',
                    marker=dict(size=10, color=color, symbol='diamond',
                                line=dict(width=1.5, color='white')),
                    text=evt_txt,
                    hovertemplate='%{x}<br>%{text}<extra></extra>'
                ))

            # Marqueur point bas
            if pb_date and pb_date != f"{now.day:02d}/{m_now+1:02d}":
                pb_color = "#E24B4A" if statut == 'danger' else "#D97706"
                fig_c.add_trace(go.Scatter(
                    x=[pb_date], y=[pb_sol],
                    mode='markers+text',
                    name='Point bas',
                    marker=dict(size=12, color=pb_color, symbol='triangle-down'),
                    text=[f"Min: {fmt2(pb_sol)}"],
                    textposition='bottom center',
                    hovertemplate=f'Point le plus bas<br>{fmt2(pb_sol)}<extra></extra>'
                ))

            # Ligne verticale aujourd'hui
            if today_str in x_vals:
                fig_c.add_shape(type='line', x0=today_str, x1=today_str, y0=0, y1=1,
                                xref='x', yref='paper',
                                line=dict(dash='dot', color='gray', width=1.5))
                fig_c.add_annotation(x=today_str, y=1, yref='paper',
                                     text="Aujourd'hui", showarrow=False,
                                     xanchor='left', yanchor='top',
                                     font=dict(size=11, color='gray'))

            # Ligne 0
            fig_c.add_hline(y=0, line_dash="solid", line_color="rgba(0,0,0,0.2)", line_width=1)

            # Ligne découvert
            if od > 0:
                fig_c.add_hline(
                    y=limite, line_dash="dash", line_color="#E24B4A",
                    line_width=1.5, opacity=0.7,
                    annotation_text=f"Limite découvert ({fmt2(limite)})",
                    annotation_position="bottom right"
                )

            fig_c.update_layout(
                height=300,
                margin=dict(t=20, b=40, l=50, r=20),
                showlegend=False,
                yaxis_title="Solde (€)",
                hovermode='x unified',
                plot_bgcolor='rgba(0,0,0,0)'
            )
            st.plotly_chart(fig_c, width="stretch")

        # ══ 3. COLONNES : POINT BAS + ÉVÉNEMENTS + RECOMMANDATION ══════════
        col_pb, col_evts = st.columns([1, 2])

        with col_pb:
            st.markdown("**📉 Point le plus bas**")
            pb_color_txt = "#E24B4A" if pb_sol < 0 else ("#D97706" if pb_sol < 300 else "#1D9E75")
            st.markdown(f"""
            <div style="border:1px solid #e0e0e0;border-radius:10px;padding:14px;text-align:center;">
                <div style="font-size:13px;color:#888;margin-bottom:4px;">{pb_date}</div>
                <div style="font-size:24px;font-weight:700;color:{pb_color_txt}">{fmt2(pb_sol)}</div>
                {"<div style='font-size:11px;color:#E24B4A;margin-top:4px;'>⚠️ Sous la limite découvert</div>" if pb_sol < limite else ""}
            </div>""", unsafe_allow_html=True)

            # Encours MC sur CA
            if cpt_cockpit == 'ca':
                mc_enc = mc_depenses_reelles(m_now, y_now, jusqu_au=now)
                mc_rest = mc_depenses_reelles(m_now, y_now) + mc_rec_non_appliquees(m_now, y_now) - mc_enc
                st.markdown(f"""
                <div style="border:1px solid #e0e0e0;border-radius:10px;padding:12px;text-align:center;margin-top:8px;">
                    <div style="font-size:11px;color:#888;">Encours MC à ce jour</div>
                    <div style="font-size:18px;font-weight:600;color:{COMPTES['mc']['color']}">−{fmt2(mc_enc)}</div>
                    <div style="font-size:11px;color:#888;margin-top:2px;">Restant à prélever : −{fmt2(mc_rest)}</div>
                </div>""", unsafe_allow_html=True)

        with col_evts:
            st.markdown("**📅 Événements à venir**")
            all_evts = [(j[0], n, d) for j in proj['jours'] for n, d in j[2]]
            if all_evts:
                for date_e, nom_e, delta_e in all_evts:
                    sign = "+" if delta_e > 0 else ""
                    color_e = "#1D9E75" if delta_e > 0 else "#E24B4A"
                    st.markdown(
                        f"<div style='padding:4px 0;border-bottom:1px solid #f0f0f0;font-size:13px;'>"
                        f"<span style='color:#888;min-width:50px;display:inline-block'>{date_e}</span>"
                        f" {nom_e} "
                        f"<strong style='color:{color_e}'>{sign}{fmt2(delta_e)}</strong></div>",
                        unsafe_allow_html=True
                    )
            else:
                st.info("Aucun événement planifié jusqu'à fin de mois.")

        # ══ 4. RECOMMANDATION ══════════════════════════════════════════════
        st.markdown("---")
        if statut == 'ok':
            if marge > 1000:
                reco = f"✓ La trésorerie reste largement positive tout le mois. Marge confortable de {fmt2(marge)}."
            else:
                reco = f"✓ La trésorerie reste positive tout le mois. Point bas à {fmt2(pb_sol)} le {pb_date}."
            st.success(reco)
        elif statut == 'warn':
            reco = f"⚠️ La trésorerie descend sous {fmt2(limite + 300)} à partir du {pb_date} (point bas : {fmt2(pb_sol)})."
            if proj['manque'] > 0:
                reco += f" Manque estimé : {fmt2(proj['manque'])}."
            st.warning(reco)
        else:
            reco = f"🔴 Dépassement du découvert autorisé prévu — point bas : {fmt2(pb_sol)} le {pb_date}."
            reco += f"\n\nMontant manquant estimé : **{fmt2(proj['manque'])}**."
            st.error(reco)

    st.markdown("---")

    # ══ 5. SOLDES + ALERTES (version compacte) ════════════════════════════
    cols2 = st.columns(2)
    cpts_affich2 = [(k,v) for k,v in COMPTES.items() if k != 'mc']
    for i, (cpt_id, cpt) in enumerate(cpts_affich2):
        with cols2[i]:
            solde = solde_a_date(cpt_id)
            od2 = D['overdraft'].get(cpt_id, 0)
            deb = get_sol(cpt_id, m_now, y_now)
            status2 = 'ok'
            if solde is not None and solde < -od2: status2 = 'danger'
            elif solde is not None and solde < (-od2 + 300): status2 = 'warn'
            # Encours MC sur CA
            mc_encours_html = ""
            if cpt_id == 'ca':
                mc_encours = mc_depenses_reelles(m_now, y_now, jusqu_au=now)
                mc_color_h = COMPTES['mc']['color']
                mc_encours_html = (f"<hr style='border:none;border-top:1px solid #e0e0e0;margin:6px 0'>"
                                   f"<small style='color:#888'>Encours MC à ce jour</small><br>"
                                   f"<span style='font-size:14px;font-weight:600;color:{mc_color_h}'>−{fmt2(mc_encours)}</span>")
            st.markdown(f"""
            <div class="metric-card today-{status2}">
                <strong style="font-size:13px">{cpt['label']}</strong>
                <span style="float:right;font-size:11px;color:#888">début : {fmt2(deb) if deb is not None else '—'}</span><br>
                <span style="font-size:20px;font-weight:700;color:{'#E24B4A' if (solde or 0)<0 else '#1D9E75'}">{fmt2(solde)}</span>
                <small style="color:#888;display:block">Découvert autorisé : {fmt2(-od2)}</small>
                {mc_encours_html}
            </div>""", unsafe_allow_html=True)

    # Alertes
    has_alert = False
    for cpt_id2 in ['ca', 'mb']:
        for typ, msg in get_alerts(cpt_id2):
            has_alert = True
            st.markdown(f'<div class="alert-{typ}"><strong>{COMPTES[cpt_id2]["label"]}</strong> — {msg}</div>',
                        unsafe_allow_html=True)
    if not has_alert:
        st.markdown('<div class="alert-ok">✓ Tous les comptes sont en ordre.</div>', unsafe_allow_html=True)

    # Découverts modifiables
    with st.expander("⚙️ Modifier les découverts autorisés", expanded=False):
        for cpt_id3, cpt3 in COMPTES.items():
            new_od = st.number_input(cpt3['label'], value=float(D['overdraft'].get(cpt_id3,0)),
                                     step=50.0, key=f"od_{cpt_id3}")
            if new_od != D['overdraft'].get(cpt_id3,0):
                D['overdraft'][cpt_id3] = new_od; persist()

    st.markdown("---")
    st.markdown("**Dernières transactions du mois**")
    tx_now = sorted(tx_of_month(m_now, y_now), key=lambda t: t['date'], reverse=True)[:8]
    if tx_now:
        st.dataframe(pd.DataFrame([{
            'Date': datetime.strptime(t['date'],'%Y-%m-%d').strftime('%d/%m/%Y'),
            'Compte': COMPTES[t['compte']]['label'].split()[0],
            'Description': t.get('note') or t['categorie'],
            'Montant': f"{'−' if t['type']=='depense' else '+'}{fmt2(t['montant'])}"
        } for t in tx_now]), width="stretch", hide_index=True)
    else:
        st.info("Aucune transaction ce mois.")

# ══════════════════════════════════════════════════════════════════════════════
# MOIS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.subheader(f"{MOIS[M]} {Y}")
    sol_cols = st.columns(2)
    for i, (cpt_id, cpt) in enumerate((k,v) for k,v in COMPTES.items() if k != 'mc'):
        with sol_cols[i]:
            deb = get_sol(cpt_id, M, Y)
            tx_m = tx_of_month(M, Y)
            entrees = sum(t['montant'] for t in tx_m if t['compte']==cpt_id and t['type']=='revenu')
            sorties = sum(t['montant'] for t in tx_m if t['compte']==cpt_id and t['type']=='depense')
            # Pour CA : ajouter les dépenses MC affectées à ce mois dans les sorties
            mc_ce_mois = mc_depenses_reelles(M, Y) if cpt_id == 'ca' else 0.0
            sorties_tot = sorties + mc_ce_mois
            fin = (deb + entrees - sorties_tot) if deb is not None else None
            with st.expander(f"**{cpt['label']}**", expanded=True):
                if cpt_id == 'ca':
                    c1,c2,c3,c4 = st.columns(4)
                    c1.metric("Début", fmt2(deb))
                    c2.metric("Entrées", f"+{fmt2(entrees)}", delta=None)
                    c3.metric("Sorties CA+MC", f"−{fmt2(sorties_tot)}",
                              help=f"CA direct : {fmt2(sorties)} · MC affectée : {fmt2(mc_ce_mois)}")
                    c4.metric("Fin estimé", fmt2(fin))
                    if mc_ce_mois > 0:
                        st.caption(f"dont MC affectée à ce mois : **{fmt2(mc_ce_mois)}**")
                else:
                    c1,c2,c3,c4 = st.columns(4)
                    c1.metric("Début", fmt2(deb))
                    c2.metric("Entrées", f"+{fmt2(entrees)}")
                    c3.metric("Sorties", f"−{fmt2(sorties)}")
                    c4.metric("Fin estimé", fmt2(fin))
                new_sol = st.number_input("Solde au 1er :", value=float(deb) if deb is not None else 0.0,
                                          step=10.0, key=f"sol_{cpt_id}_{M}_{Y}", format="%.2f")
                if st.button("💾 Enregistrer", key=f"sav_{cpt_id}_{M}_{Y}"):
                    set_sol(cpt_id, M, Y, new_sol); persist()
                    st.success("✓"); st.rerun()

    st.divider()
    rev = sum(t['montant'] for t in TX_CUR if t['type']=='revenu')
    dep = sum(t['montant'] for t in TX_CUR if t['type']=='depense')
    # MC affectée à ce mois (tous comptes confondus dans le filtre courant, ou sur CA si filtre all)
    mc_glob = mc_depenses_reelles(M, Y)
    dep_tot = dep + (mc_glob if FCPT in ('all','ca') else 0)
    k1,k2,k3,k4 = st.columns(4)
    k1.metric("Entrées", fmt(rev))
    k2.metric("Sorties directes", fmt(dep))
    k3.metric("dont MC", fmt(mc_glob) if FCPT in ('all','ca') else "—")
    k4.metric("Variation nette", f"{'+' if rev-dep_tot>=0 else ''}{fmt(rev-dep_tot)}")
    st.divider()
    g1,g2 = st.columns(2)
    with g1:
        st.markdown("**Par catégorie**")
        dbc = defaultdict(float)
        for t in TX_CUR:
            if t['type']=='depense': dbc[t['categorie']] += t['montant']
        if dbc:
            df_c = pd.DataFrame(sorted(dbc.items(),key=lambda x:-x[1])[:8], columns=['Cat','Montant'])
            fig = go.Figure(go.Bar(x=df_c['Cat'], y=df_c['Montant'], marker_color=CC[:len(df_c)],
                                   text=[fmt(v) for v in df_c['Montant']], textposition='outside'))
            fig.update_layout(height=300, margin=dict(t=20,b=80), showlegend=False, xaxis_tickangle=-30)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("Aucune dépense.")
    with g2:
        st.markdown("**Par compte**")
        dba = {c: sum(t['montant'] for t in TX_CUR if t['type']=='depense' and t['compte']==c) for c in COMPTES}
        dba = {k:v for k,v in dba.items() if v>0}
        if dba:
            fig2 = go.Figure(go.Pie(
                labels=[COMPTES[k]['label'] for k in dba], values=list(dba.values()),
                marker_colors=[COMPTES[k]['color'] for k in dba], hole=0.4))
            fig2.update_layout(height=300, margin=dict(t=20,b=20))
            st.plotly_chart(fig2, width="stretch")
        else:
            st.info("Aucune dépense.")

# ══════════════════════════════════════════════════════════════════════════════
# TRANSACTIONS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.subheader(f"Transactions — {MOIS[M]} {Y}")
    tf1, tf2 = st.columns(2)
    with tf1:
        fopts_tx = {'all': 'Tous les comptes', **{k: v['label'] for k,v in COMPTES.items()}}
        filt_cpt_tx = st.selectbox("Filtrer par compte", list(fopts_tx.keys()),
                                    format_func=lambda x: fopts_tx[x], key="filt_cpt_tx")
    with tf2:
        tx_pool = [t for t in TX_CUR if filt_cpt_tx=='all' or t['compte']==filt_cpt_tx]
        cats_filt = ['Toutes'] + sorted(set(t['categorie'] for t in tx_pool))
        filt_cat = st.selectbox("Filtrer par catégorie", cats_filt, key="filt_cat_tx")
    tx_show = sorted(
        tx_pool if filt_cat=='Toutes' else [t for t in tx_pool if t['categorie']==filt_cat],
        key=lambda t: t['date'], reverse=True
    )
    if not tx_show:
        st.info("Aucune transaction.")
    else:
        for t in tx_show:
            d = datetime.strptime(t['date'],'%Y-%m-%d')
            cpt = COMPTES.get(t['compte'],{'label':t['compte']})
            is_exc = t.get('exceptionnel', False)
            exc_badge = " ⭐" if is_exc else ""
            with st.expander(f"{'−' if t['type']=='depense' else '+'}{fmt2(t['montant'])} — {t.get('note') or t['categorie']} — {d.strftime('%d/%m/%Y')}{exc_badge}", expanded=False):
                # Bouton rapide exceptionnel HORS formulaire
                btn_label = "⭐ Marquer normale" if is_exc else "⭐ Marquer exceptionnelle"
                if st.button(btn_label, key=f"exc_quick_{t['id']}"):
                    idx = next(i for i,x in enumerate(D['tx']) if x['id']==t['id'])
                    D['tx'][idx] = {**t, 'exceptionnel': not is_exc}
                    persist(); st.rerun()
                if is_exc:
                    st.caption("⭐ Transaction exceptionnelle — exclue du calcul de prévision")
                with st.form(key=f"edit_tx_{t['id']}"):
                    ef1,ef2 = st.columns(2)
                    with ef1:
                        new_date = st.date_input("Date", value=d.date(), key=f"td_{t['id']}")
                        new_cpt = st.selectbox("Compte", list(COMPTES.keys()),
                                               index=list(COMPTES.keys()).index(t['compte']),
                                               format_func=lambda x: COMPTES[x]['label'],
                                               key=f"tc_{t['id']}")
                        new_type = st.radio("Type", ['depense','revenu'],
                                            index=0 if t['type']=='depense' else 1,
                                            format_func=lambda x: '💸 Dépense' if x=='depense' else '💰 Revenu',
                                            horizontal=True, key=f"tt_{t['id']}")
                    with ef2:
                        new_cat = st.selectbox("Catégorie", visible_cats(),
                                               index=visible_cats().index(t['categorie']) if t['categorie'] in visible_cats() else 0,
                                               key=f"tcat_{t['id']}")
                        new_mnt = st.number_input("Montant €", value=float(t['montant']),
                                                  step=0.01, format="%.2f", key=f"tm_{t['id']}")
                        new_note = st.text_input("Note", value=t.get('note',''), key=f"tn_{t['id']}")
                        new_exc = st.checkbox("⭐ Exceptionnelle (exclue du prévisionnel)",
                                              value=is_exc, key=f"texc_{t['id']}")

                    new_affm, new_affy = t.get('affM'), t.get('affY')
                    if new_cpt == 'mc':
                        mc1,mc2 = st.columns(2)
                        new_affm = mc1.selectbox("Mois affectation", range(12),
                                                 index=int(t['affM']) if t.get('affM') is not None else d.month-1,
                                                 format_func=lambda x: MOIS[x], key=f"tam_{t['id']}")
                        new_affy = mc2.selectbox("Année", [2024,2025,2026,2027],
                                                 index=[2024,2025,2026,2027].index(int(t['affY'])) if t.get('affY') in [2024,2025,2026,2027] else 2,
                                                 key=f"tay_{t['id']}")

                    col_save, col_del = st.columns([3,1])
                    if col_save.form_submit_button("💾 Enregistrer", width="stretch"):
                        idx = next(i for i,x in enumerate(D['tx']) if x['id']==t['id'])
                        D['tx'][idx] = {**t, 'date': new_date.strftime('%Y-%m-%d'),
                                        'compte': new_cpt, 'categorie': new_cat,
                                        'montant': float(new_mnt), 'type': new_type,
                                        'note': new_note, 'affM': new_affm, 'affY': new_affy,
                                        'exceptionnel': new_exc}
                        persist(); st.success("✓"); st.rerun()
                if st.button("🗑 Supprimer", key=f"del_tx_{t['id']}"):
                    D['tx'] = [x for x in D['tx'] if x['id']!=t['id']]
                    persist(); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# SAISIE
# ══════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.subheader("Ajouter une transaction")
    # Sélection compte HORS formulaire → persiste entre saisies
    cpt_keys = list(COMPTES.keys())
    tx_cpt = st.selectbox(
        "Compte", cpt_keys,
        index=cpt_keys.index(st.session_state.last_saisie_cpt),
        format_func=lambda x: COMPTES[x]['label'],
        key="saisie_cpt_select"
    )
    if tx_cpt != st.session_state.last_saisie_cpt:
        st.session_state.last_saisie_cpt = tx_cpt
        st.rerun()
    if tx_cpt == 'mc':
        st.info("💳 **Mastercard débit différé** — le mois d'affectation est demandé ci-dessous.")
    with st.form("add_tx", clear_on_submit=True):
        fc1,fc2 = st.columns(2)
        with fc1:
            tx_date = st.date_input("Date (JJ/MM/AAAA)", value=date.today(), format="DD/MM/YYYY")
            tx_type = st.radio("Type", ['depense','revenu'],
                               format_func=lambda x: '💸 Dépense' if x=='depense' else '💰 Revenu',
                               horizontal=True)
        with fc2:
            tx_cat = st.selectbox("Catégorie", visible_cats())
            tx_mnt = st.number_input("Montant (€)", min_value=0.01, step=0.01, format="%.2f")
            tx_note = st.text_input("Note", placeholder="Description…")
            tx_exc = st.checkbox("⭐ Exceptionnelle (exclue du prévisionnel)", value=False)
        aff_m = aff_y = None
        if tx_cpt == 'mc':
            m1,m2 = st.columns(2)
            aff_m = m1.selectbox("Mois affectation", range(12), index=datetime.now().month-1, format_func=lambda x: MOIS[x])
            aff_y = m2.selectbox("Année", [2024,2025,2026,2027], index=2)
        if st.form_submit_button("✅ Ajouter", type="primary", width="stretch"):
            new_tx = {'id':f"tx_{int(datetime.now().timestamp()*1000)}",
                      'date':tx_date.strftime('%Y-%m-%d'), 'compte':tx_cpt,
                      'categorie':tx_cat, 'montant':float(tx_mnt),
                      'type':tx_type, 'note':tx_note}
            if tx_cpt=='mc' and aff_m is not None:
                new_tx['affM'] = aff_m; new_tx['affY'] = aff_y
            if tx_exc: new_tx['exceptionnel'] = True
            D['tx'].append(new_tx); persist()
            st.success(f"✓ {COMPTES[tx_cpt]['label']} — {fmt2(tx_mnt)} — {tx_cat}")
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# RÉCURRENTES
# ══════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.subheader(f"Récurrentes — {MOIS[M]} {Y}")
    applied = sum(1 for r in D['rec'] if rec_applied(r['id'],M,Y))
    st.info(f"**{applied} / {len(D['rec'])}** charges appliquées ce mois.")
    if st.button("⚡ Appliquer toutes au mois en cours", type="primary"):
        added = 0
        for r in D['rec']:
            if rec_applied(r['id'],M,Y): continue
            j = min(r['jour'],28)
            D['tx'].append({'id':f"tx_{int(datetime.now().timestamp()*1000)}_{added}",
                            'date':f"{Y}-{M+1:02d}-{j:02d}", 'compte':r['compte'],
                            'categorie':r['cat'], 'montant':r['mnt'],
                            'type':r['type'], 'note':r['nom'], 'recId':r['id']})
            added += 1
        persist(); st.success(f"✓ {added} appliquée(s)."); st.rerun()

    st.divider()
    # Filtre par compte
    fopts_rec = {'all': 'Tous les comptes', **{k: v['label'] for k,v in COMPTES.items()}}
    filt_rec_cpt = st.selectbox("Filtrer par compte", list(fopts_rec.keys()),
                                 format_func=lambda x: fopts_rec[x], key="filt_rec_cpt")
    rec_display = [r for r in D['rec'] if filt_rec_cpt == 'all' or r['compte'] == filt_rec_cpt]

    for r in rec_display:
        done = rec_applied(r['id'],M,Y)
        icon = "✅" if done else "⏳"
        cpt = COMPTES.get(r['compte'],{'label':r['compte']})
        with st.expander(f"{icon} **{r['nom']}** — {'+' if r['type']=='revenu' else '−'}{fmt2(r['mnt'])} — {cpt['label'].split()[0]} — j.{r['jour']}"):
            with st.form(f"edit_rec_{r['id']}"):
                er1,er2 = st.columns(2)
                with er1:
                    rn = st.text_input("Nom", value=r['nom'])
                    rc = st.selectbox("Compte", list(COMPTES.keys()),
                                      index=list(COMPTES.keys()).index(r['compte']),
                                      format_func=lambda x: COMPTES[x]['label'])
                    rt = st.radio("Type", ['depense','revenu'],
                                  index=0 if r['type']=='depense' else 1,
                                  format_func=lambda x: '💸 Dépense' if x=='depense' else '💰 Revenu',
                                  horizontal=True, key=f"rtype_{r['id']}")
                with er2:
                    rcat = st.selectbox("Catégorie", visible_cats(),
                                        index=visible_cats().index(r['cat']) if r['cat'] in visible_cats() else 0)
                    rmnt = st.number_input("Montant €", value=float(r['mnt']), step=0.01, format="%.2f")
                    rjour = st.number_input("Jour du mois", value=min(int(r["jour"]), 28), min_value=1, max_value=28)
                if st.form_submit_button("💾 Enregistrer", width="stretch"):
                    idx = next(i for i,x in enumerate(D['rec']) if x['id']==r['id'])
                    D['rec'][idx] = {**r,'nom':rn,'compte':rc,'cat':rcat,'mnt':float(rmnt),'type':rt,'jour':int(rjour)}
                    persist(); st.success("✓"); st.rerun()
            if st.button("🗑 Supprimer", key=f"del_r_{r['id']}"):
                D['rec'] = [x for x in D['rec'] if x['id']!=r['id']]
                persist(); st.rerun()

    st.divider()
    st.markdown("**Ajouter une charge récurrente**")
    with st.form("add_rec", clear_on_submit=True):
        ar1,ar2 = st.columns(2)
        with ar1:
            rn2 = st.text_input("Nom")
            rc2 = st.selectbox("Compte", list(COMPTES.keys()), format_func=lambda x: COMPTES[x]['label'], key="arc")
            rt2 = st.radio("Type", ['depense','revenu'],
                           format_func=lambda x: '💸 Dépense' if x=='depense' else '💰 Revenu',
                           horizontal=True, key="art")
        with ar2:
            rcat2 = st.selectbox("Catégorie", visible_cats(), key="arcat")
            rmnt2 = st.number_input("Montant €", min_value=0.01, step=0.01, format="%.2f", key="armnt")
            rjour2 = st.number_input("Jour du mois", min_value=1, max_value=28, value=5, key="arjour")
        if st.form_submit_button("✅ Enregistrer", width="stretch"):
            D['rec'].append({'id':f"r_{int(datetime.now().timestamp()*1000)}",'nom':rn2,
                             'compte':rc2,'cat':rcat2,'mnt':float(rmnt2),'type':rt2,'jour':int(rjour2)})
            persist(); st.success("✓"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PRÉVISIONNEL — vue consolidée foyer
# ══════════════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.subheader("Prévisionnel global du foyer")
    st.caption(
        "Prévision indicative basée sur l'historique disponible. "
        "Plus l'historique grandit, plus l'estimation devient fiable. "
        "**Passé** : réel · **Futur** : pointillé avec intervalle de confiance · MC intégrée dans CA"
    )

    months, daily_series, monthly_series, fc_warnings = build_forecast_v2()

    for w in fc_warnings:
        st.warning(w)

    now_pv = datetime.now()

    # ── Prévision par catégorie pour les mois futurs ───────────────────────
    future_months_list = [months[i] for i in range(7, 12)]
    fc_by_cpt = {cpt_id: prevision_depenses(cpt_id, future_months_list)
                 for cpt_id in ['ca', 'mb']}

    def month_bars(cpt_id):
        rows = []
        fc_list = fc_by_cpt[cpt_id]
        fc_idx = 0
        for idx, (m, y) in enumerate(months):
            rel = idx - 6
            is_fc = rel > 0
            label = f"{MOIS_COURT[m]} {y}"
            fc_detail = None

            if not is_fc:
                tx_m = [t for t in D['tx'] if t['compte']==cpt_id and aff_key(t)==(y, m)]
                entrees = sum(t['montant'] for t in tx_m if t['type']=='revenu')
                sorties = sum(t['montant'] for t in tx_m if t['type']=='depense')
                if cpt_id == 'ca':
                    sorties += mc_depenses_reelles(m, y)
                sol_min = sol_max = None
            else:
                fc = fc_list[fc_idx] if fc_idx < len(fc_list) else None
                fc_idx += 1
                rec_e = sum(r['mnt'] for r in D['rec'] if r['compte']==cpt_id and r['type']=='revenu')
                if fc:
                    entrees = rec_e
                    sorties = fc['total_moyen']
                    fc_detail = fc['par_categorie']
                else:
                    entrees = rec_e
                    sorties = 0.0
                sol_min = sol_max = None

            ms_entry = next(((v,vmi,vma) for v,vmi,vma,lbl,ifc in monthly_series[cpt_id] if lbl==label), (None,None,None))
            sol_fin, sol_min_s, sol_max_s = ms_entry
            if is_fc:
                sol_min = sol_min_s
                sol_max = sol_max_s

            rows.append({
                'label': label, 'entrees': entrees, 'sorties': sorties,
                'sol': sol_fin, 'sol_min': sol_min, 'sol_max': sol_max,
                'is_fc': is_fc, 'fc_detail': fc_detail
            })
        return rows

    rows_ca = month_bars('ca')
    rows_mb = month_bars('mb')

    # ── Helper : agréger CA + MB sans recalculer ───────────────────────────
    def agreger_rows(rca, rmb):
        """
        Agrège les rows CA et MB mois par mois.
        Entrées/sorties : somme simple (les virements internes se neutralisent).
        Solde global : somme des soldes individuels quand les deux sont disponibles.
        IC global : somme des IC individuels.
        """
        result = []
        for a, b in zip(rca, rmb):
            sol_g     = (a['sol'] + b['sol']) if (a['sol'] is not None and b['sol'] is not None) else None
            sol_min_g = (a['sol_min'] + b['sol_min']) if (a['sol_min'] is not None and b['sol_min'] is not None) else None
            sol_max_g = (a['sol_max'] + b['sol_max']) if (a['sol_max'] is not None and b['sol_max'] is not None) else None
            result.append({
                'label':    a['label'],
                'entrees':  a['entrees']  + b['entrees'],
                'sorties':  a['sorties']  + b['sorties'],
                'sol':      sol_g,
                'sol_min':  sol_min_g,
                'sol_max':  sol_max_g,
                'is_fc':    a['is_fc'],
            })
        return result

    rows_global = agreger_rows(rows_ca, rows_mb)

    # ══ GRAPHIQUE GLOBAL ══════════════════════════════════════════════════
    labels_g  = [r['label']   for r in rows_global]
    entrees_g = [r['entrees'] for r in rows_global]
    sorties_g = [r['sorties'] for r in rows_global]
    sols_g    = [r['sol']     for r in rows_global]
    is_fc_g   = [r['is_fc']   for r in rows_global]

    op_in  = [0.4 if f else 1.0 for f in is_fc_g]
    op_out = [0.4 if f else 1.0 for f in is_fc_g]

    COLOR_GLOBAL = "#5A2070"   # Aubergine secondaire
    r_g, g_g, b_g = int(COLOR_GLOBAL[1:3],16), int(COLOR_GLOBAL[3:5],16), int(COLOR_GLOBAL[5:7],16)

    fig_g = go.Figure()

    # Zone rouge sous 0
    sol_vals_g = [s for s in sols_g if s is not None]
    y_min_g = min(sol_vals_g)*1.15 if sol_vals_g else -1000
    fig_g.add_hrect(y0=y_min_g, y1=0, fillcolor="rgba(220,50,50,0.04)", line_width=0)

    # Barres entrées
    fig_g.add_trace(go.Bar(
        x=labels_g, y=entrees_g,
        name="Entrées foyer",
        marker_color=[f"rgba(29,158,117,{o})" for o in op_in],
        offsetgroup=0,
        hovertemplate='%{x}<br>Entrées : %{y:,.0f} €<extra></extra>'
    ))

    # Barres sorties (vers le bas)
    fig_g.add_trace(go.Bar(
        x=labels_g, y=[-s for s in sorties_g],
        name="Sorties foyer",
        marker_color=[f"rgba(226,75,74,{o})" for o in op_out],
        offsetgroup=1,
        hovertemplate='%{x}<br>Sorties : %{customdata:,.0f} €<extra></extra>',
        customdata=sorties_g
    ))

    # Ligne solde global passé
    real_g = [(i, v) for i, v in enumerate(sols_g) if v is not None and not is_fc_g[i]]
    fc_g   = [(i, v) for i, v in enumerate(sols_g) if v is not None and is_fc_g[i]]

    if real_g:
        fig_g.add_trace(go.Scatter(
            x=[labels_g[i] for i, v in real_g],
            y=[v for i, v in real_g],
            mode='lines+markers',
            name="Solde global",
            line=dict(color=COLOR_GLOBAL, width=3),
            marker=dict(size=7),
            hovertemplate='%{x}<br>Solde : %{y:,.0f} €<extra></extra>'
        ))

    # IC + ligne pointillée future
    if real_g and fc_g:
        anchor_i, anchor_v = real_g[-1]
        x_fc_g = [labels_g[anchor_i]] + [labels_g[i] for i, v in fc_g]
        y_fc_g = [anchor_v] + [v for i, v in fc_g]
        sol_mins_g = [rows_global[i]['sol_min'] for i, v in fc_g]
        sol_maxs_g = [rows_global[i]['sol_max'] for i, v in fc_g]
        y_lo_g = [anchor_v] + [v if v is not None else y_fc_g[j+1] for j, v in enumerate(sol_mins_g)]
        y_hi_g = [anchor_v] + [v if v is not None else y_fc_g[j+1] for j, v in enumerate(sol_maxs_g)]

        # Zone IC
        fig_g.add_trace(go.Scatter(
            x=x_fc_g + x_fc_g[::-1],
            y=y_hi_g + y_lo_g[::-1],
            fill='toself',
            fillcolor=f"rgba({r_g},{g_g},{b_g},0.10)",
            line=dict(width=0),
            showlegend=False,
            hoverinfo='skip',
            name='IC global'
        ))
        # Ligne centrale
        fig_g.add_trace(go.Scatter(
            x=x_fc_g, y=y_fc_g,
            mode='lines+markers',
            name="Solde global estimé",
            showlegend=False,
            line=dict(color=COLOR_GLOBAL, width=2, dash='dot'),
            marker=dict(size=7, symbol='circle-open'),
            hovertemplate='%{x}<br>Estimé : %{y:,.0f} €<extra></extra>'
        ))

    # Ligne 0
    fig_g.add_hline(y=0, line_color="rgba(0,0,0,0.15)", line_width=1)

    # Ligne verticale aujourd'hui
    today_lbl = f"{MOIS_COURT[now_pv.month-1]} {now_pv.year}"
    if today_lbl in labels_g:
        fig_g.add_shape(type='line', x0=today_lbl, x1=today_lbl, y0=0, y1=1,
                        xref='x', yref='paper',
                        line=dict(dash='dot', color='gray', width=1.5))

    fig_g.update_layout(
        barmode='group',
        height=400,
        hovermode='x unified',
        margin=dict(t=20, b=60, l=60, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
        yaxis_title="€",
        bargap=0.2, bargroupgap=0.05,
        plot_bgcolor='rgba(0,0,0,0)'
    )
    st.plotly_chart(fig_g, width="stretch")

    # ══ CARTES SYNTHÉTIQUES CA / MB ═══════════════════════════════════════
    card_cols = st.columns(2)
    for ci, cpt_id in enumerate(['ca', 'mb']):
        rows_c = rows_ca if cpt_id == 'ca' else rows_mb
        cpt    = COMPTES[cpt_id]
        color  = cpt['color']

        # Solde prévu fin de période (dernier mois futur non-None)
        fc_rows = [r for r in rows_c if r['is_fc'] and r['sol'] is not None]
        sol_fin_c  = fc_rows[-1]['sol']  if fc_rows else None
        sol_min_fc = [r['sol'] for r in fc_rows if r['sol'] is not None]
        point_bas  = min(sol_min_fc) if sol_min_fc else sol_fin_c
        pb_label   = next((r['label'] for r in fc_rows if r['sol'] == point_bas), "—")

        # Tendance : pente entre premier et dernier sol futur
        if len(sol_min_fc) >= 2:
            delta_fc = sol_min_fc[-1] - sol_min_fc[0]
            if delta_fc > 200:   tendance_txt, tendance_col = "↗ En hausse",  "#1D9E75"
            elif delta_fc < -200: tendance_txt, tendance_col = "↘ En baisse",  "#E24B4A"
            else:                 tendance_txt, tendance_col = "→ Stable",     "#888"
        else:
            tendance_txt, tendance_col = "— Insuffisant", "#888"

        # Vigilance
        od_c = D['overdraft'].get(cpt_id, 0)
        if point_bas is not None and point_bas < -od_c:
            vig_txt, vig_bg, vig_border = "🔴 Risque découvert", "#fdf0f0", "#E24B4A"
        elif point_bas is not None and point_bas < (-od_c + 300):
            vig_txt, vig_bg, vig_border = "🟠 Vigilance", "#fff8e6", "#D97706"
        else:
            vig_txt, vig_bg, vig_border = "🟢 OK", "#f0faf4", "#1D9E75"

        sol_fin_str  = fmt2(sol_fin_c)  if sol_fin_c  is not None else "—"
        point_bas_str = fmt2(point_bas) if point_bas  is not None else "—"
        pb_color = "#E24B4A" if (point_bas or 0) < 0 else "#555"

        with card_cols[ci]:
            st.markdown(f"""
            <div style="border:1.5px solid {vig_border};border-radius:12px;
                        background:{vig_bg};padding:16px 18px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                    <strong style="font-size:14px;color:{color}">{cpt['label']}</strong>
                    <span style="font-size:12px;font-weight:600;color:{vig_border}">{vig_txt}</span>
                </div>
                <div style="display:flex;gap:16px;">
                    <div style="flex:1;text-align:center;">
                        <div style="font-size:11px;color:#888;margin-bottom:2px;">Solde fin période</div>
                        <div style="font-size:18px;font-weight:700;
                             color:{'#E24B4A' if (sol_fin_c or 0)<0 else '#1D9E75'}">{sol_fin_str}</div>
                    </div>
                    <div style="flex:1;text-align:center;">
                        <div style="font-size:11px;color:#888;margin-bottom:2px;">Point bas ({pb_label})</div>
                        <div style="font-size:16px;font-weight:600;color:{pb_color}">{point_bas_str}</div>
                    </div>
                    <div style="flex:1;text-align:center;">
                        <div style="font-size:11px;color:#888;margin-bottom:2px;">Tendance</div>
                        <div style="font-size:14px;font-weight:600;color:{tendance_col}">{tendance_txt}</div>
                    </div>
                </div>
            </div>""", unsafe_allow_html=True)

    st.markdown("")  # espacement

    # ══ EXPANDER : DÉTAIL PAR COMPTE ══════════════════════════════════════
    with st.expander("📊 Voir le détail par compte", expanded=False):
        for cpt_id in ['ca', 'mb']:
            cpt = COMPTES[cpt_id]
            color_sol = cpt['color']
            rows = rows_ca if cpt_id == 'ca' else rows_mb
            r_c = int(color_sol[1:3],16)
            g_c = int(color_sol[3:5],16)
            b_c = int(color_sol[5:7],16)

            labels    = [r['label']   for r in rows]
            entrees   = [r['entrees'] for r in rows]
            sorties   = [r['sorties'] for r in rows]
            sols      = [r['sol']     for r in rows]
            is_fc     = [r['is_fc']   for r in rows]
            op_i = [0.4 if f else 1.0 for f in is_fc]

            fig_d = go.Figure()
            sol_vals_d = [s for s in sols if s is not None]
            y_min_d = min(sol_vals_d)*1.15 if sol_vals_d else -500
            fig_d.add_hrect(y0=y_min_d, y1=0, fillcolor="rgba(220,50,50,0.05)", line_width=0)

            fig_d.add_trace(go.Bar(x=labels, y=entrees, name="Entrées",
                marker_color=[f"rgba(29,158,117,{o})" for o in op_i],
                offsetgroup=0, hovertemplate='%{x}<br>Entrées : %{y:,.0f} €<extra></extra>'))
            fig_d.add_trace(go.Bar(x=labels, y=[-s for s in sorties], name="Sorties",
                marker_color=[f"rgba(226,75,74,{o})" for o in op_i],
                offsetgroup=1, customdata=sorties,
                hovertemplate='%{x}<br>Sorties : %{customdata:,.0f} €<extra></extra>'))

            real_d = [(i,v) for i,v in enumerate(sols) if v is not None and not is_fc[i]]
            fc_d   = [(i,v) for i,v in enumerate(sols) if v is not None and is_fc[i]]
            if real_d:
                fig_d.add_trace(go.Scatter(
                    x=[labels[i] for i,v in real_d], y=[v for i,v in real_d],
                    mode='lines+markers', name=f"Solde {cpt['label'].split()[0]}",
                    line=dict(color=color_sol, width=2.5), marker=dict(size=6),
                    hovertemplate='%{x}<br>Solde : %{y:,.0f} €<extra></extra>'))
            if real_d and fc_d:
                ai, av = real_d[-1]
                x_fc_d = [labels[ai]] + [labels[i] for i,v in fc_d]
                y_fc_d = [av] + [v for i,v in fc_d]
                y_lo_d = [av] + [rows[i]['sol_min'] or v for i,v in fc_d]
                y_hi_d = [av] + [rows[i]['sol_max'] or v for i,v in fc_d]
                fig_d.add_trace(go.Scatter(
                    x=x_fc_d+x_fc_d[::-1], y=y_hi_d+y_lo_d[::-1],
                    fill='toself', fillcolor=f"rgba({r_c},{g_c},{b_c},0.12)",
                    line=dict(width=0), showlegend=False, hoverinfo='skip'))
                fig_d.add_trace(go.Scatter(
                    x=x_fc_d, y=y_fc_d, mode='lines+markers', showlegend=False,
                    line=dict(color=color_sol, width=1.5, dash='dot'),
                    marker=dict(size=6, symbol='circle-open'),
                    hovertemplate='%{x}<br>Estimé : %{y:,.0f} €<extra></extra>'))

            od_v = D['overdraft'].get(cpt_id, 0)
            if od_v > 0:
                fig_d.add_hline(y=-od_v, line_dash="dash", line_color=color_sol,
                                line_width=1, opacity=0.4,
                                annotation_text="Découvert max", annotation_position="bottom right")
            if today_lbl in labels:
                fig_d.add_shape(type='line', x0=today_lbl, x1=today_lbl, y0=0, y1=1,
                                xref='x', yref='paper',
                                line=dict(dash='dot', color='gray', width=1.5))

            fig_d.update_layout(
                title=dict(text=cpt['label'], font=dict(size=13)),
                barmode='group', height=300,
                hovermode='x unified',
                margin=dict(t=35, b=50, l=50, r=20),
                legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
                yaxis_title="€", bargap=0.2, bargroupgap=0.05,
                plot_bgcolor='rgba(0,0,0,0)'
            )
            st.plotly_chart(fig_d, width="stretch")

    # ══ DÉTAIL MENSUEL COMPLET ════════════════════════════════════════════
    with st.expander("📋 Détail mensuel — entrées, sorties et catégories", expanded=False):
        TENDANCE_ICON = {"hausse": "↑", "baisse": "↓", "stable": "→", "insuffisant": "?"}

        detail_cpt = st.radio("Compte", ["ca", "mb"],
                              format_func=lambda x: COMPTES[x]["label"],
                              horizontal=True, key="detail_cpt_prev")
        rows_detail = rows_ca if detail_cpt == "ca" else rows_mb

        for r in rows_detail:
            prefix = "~" if r["is_fc"] else ""
            sol_str = fmt(r["sol"]) if r["sol"] is not None else "—"
            if r["is_fc"] and r["sol_min"] is not None and r["sol_max"] is not None:
                sol_str += f" [{fmt(r['sol_min'])} – {fmt(r['sol_max'])}]"

            # Titre du mois avec badge passé/futur et solde
            badge_color = "#888" if r["is_fc"] else "#1D9E75"
            badge_txt   = f"{prefix}Estimé" if r["is_fc"] else "Réel"
            solde_color = "#E24B4A" if (r["sol"] or 0) < 0 else "#1D9E75"

            with st.expander(
                f"{'~' if r['is_fc'] else '📅'} {r['label']} — "
                f"Entrées {fmt(r['entrees'])} · Sorties {fmt(r['sorties'])} · "
                f"Solde {sol_str}",
                expanded=False
            ):
                col_e, col_s = st.columns(2)

                # ── ENTRÉES ──────────────────────────────────────────────
                with col_e:
                    st.markdown("**💚 Entrées**")
                    if not r["is_fc"]:
                        # Passé : TX réelles
                        tx_rev = [t for t in D["tx"]
                                  if t["compte"] == detail_cpt
                                  and aff_key(t) == (int(r["label"][-4:]), [MOIS_COURT.index(r["label"][:3])] and MOIS_COURT.index(r["label"][:3]))
                                  and t["type"] == "revenu"]
                        # Extraire l'année et le mois depuis le label
                        lbl_parts = r["label"].split()
                        lbl_m = MOIS_COURT.index(lbl_parts[0])
                        lbl_y = int(lbl_parts[1])
                        tx_rev = [t for t in D["tx"]
                                  if t["compte"] == detail_cpt
                                  and aff_key(t) == (lbl_y, lbl_m)
                                  and t["type"] == "revenu"]
                        by_cat = defaultdict(float)
                        for t in tx_rev:
                            by_cat[t["categorie"]] += t["montant"]
                        if by_cat:
                            for cat, mnt in sorted(by_cat.items(), key=lambda x: -x[1]):
                                st.markdown(
                                    f"<div style='display:flex;justify-content:space-between;"
                                    f"padding:3px 0;border-bottom:1px solid #f0f0f0;font-size:13px'>"
                                    f"<span>{cat}</span>"
                                    f"<span style='color:#1D9E75;font-weight:500'>+{fmt(mnt)}</span></div>",
                                    unsafe_allow_html=True
                                )
                        else:
                            st.caption("Aucune entrée")
                        st.markdown(f"**Total : +{fmt(r['entrees'])}**")
                    else:
                        # Futur : récurrentes revenus
                        rec_rev = [(r2["nom"], r2["mnt"]) for r2 in D["rec"]
                                   if r2["compte"] == detail_cpt and r2["type"] == "revenu"]
                        for nom, mnt in sorted(rec_rev, key=lambda x: -x[1]):
                            st.markdown(
                                f"<div style='display:flex;justify-content:space-between;"
                                f"padding:3px 0;border-bottom:1px solid #f0f0f0;font-size:13px'>"
                                f"<span>🔄 {nom}</span>"
                                f"<span style='color:#1D9E75;font-weight:500'>+{fmt(mnt)}</span></div>",
                                unsafe_allow_html=True
                            )
                        if not rec_rev:
                            st.caption("Aucune récurrente revenu")
                        st.markdown(f"**Total estimé : +{fmt(r['entrees'])}**")

                # ── SORTIES ───────────────────────────────────────────────
                with col_s:
                    st.markdown("**❤️ Sorties**")
                    if not r["is_fc"]:
                        lbl_parts = r["label"].split()
                        lbl_m = MOIS_COURT.index(lbl_parts[0])
                        lbl_y = int(lbl_parts[1])
                        tx_dep = [t for t in D["tx"]
                                  if t["compte"] == detail_cpt
                                  and aff_key(t) == (lbl_y, lbl_m)
                                  and t["type"] == "depense"]
                        # Ajouter MC si CA
                        if detail_cpt == "ca":
                            tx_dep += [t for t in D["tx"]
                                       if t["compte"] == "mc"
                                       and t["type"] == "depense"
                                       and aff_key(t) == (lbl_y, lbl_m)]
                        by_cat = defaultdict(float)
                        for t in tx_dep:
                            by_cat[t["categorie"]] += t["montant"]
                        if by_cat:
                            for cat, mnt in sorted(by_cat.items(), key=lambda x: -x[1]):
                                st.markdown(
                                    f"<div style='display:flex;justify-content:space-between;"
                                    f"padding:3px 0;border-bottom:1px solid #f0f0f0;font-size:13px'>"
                                    f"<span>{cat}</span>"
                                    f"<span style='color:#E24B4A;font-weight:500'>−{fmt(mnt)}</span></div>",
                                    unsafe_allow_html=True
                                )
                        else:
                            st.caption("Aucune sortie")
                        st.markdown(f"**Total : −{fmt(r['sorties'])}**")
                    else:
                        # Futur : récurrentes dépenses + variable par catégorie
                        rec_dep = [(r2["nom"], r2["mnt"], "rec") for r2 in D["rec"]
                                   if r2["compte"] == detail_cpt and r2["type"] == "depense"]
                        if detail_cpt == "ca":
                            rec_dep += [(r2["nom"], r2["mnt"], "mc") for r2 in D["rec"]
                                        if r2["compte"] == "mc" and r2["type"] == "depense"]
                        for nom, mnt, src in sorted(rec_dep, key=lambda x: -x[1]):
                            badge = "💳" if src == "mc" else "🔄"
                            st.markdown(
                                f"<div style='display:flex;justify-content:space-between;"
                                f"padding:3px 0;border-bottom:1px solid #f0f0f0;font-size:13px'>"
                                f"<span>{badge} {nom}</span>"
                                f"<span style='color:#E24B4A;font-weight:500'>−{fmt(mnt)}</span></div>",
                                unsafe_allow_html=True
                            )
                        # Dépenses variables estimées par catégorie
                        if r["fc_detail"]:
                            st.markdown("<div style='margin-top:8px;font-size:12px;color:#888'>Variables estimées :</div>",
                                        unsafe_allow_html=True)
                            for cat, d in sorted(r["fc_detail"].items(), key=lambda x: -x[1]["moyen"]):
                                if d["moyen"] < 1: continue
                                icon = TENDANCE_ICON.get(d["tendance"], "?")
                                st.markdown(
                                    f"<div style='display:flex;justify-content:space-between;"
                                    f"padding:3px 0;border-bottom:1px solid #f5f5f5;font-size:12px;color:#555'>"
                                    f"<span>{icon} {cat}</span>"
                                    f"<span>−{fmt(d['moyen'])} "
                                    f"<small style='color:#aaa'>[{fmt(d['min'])}–{fmt(d['max'])}]</small>"
                                    f"</span></div>",
                                    unsafe_allow_html=True
                                )
                        st.markdown(f"**Total estimé : −{fmt(r['sorties'])}**")


# ══════════════════════════════════════════════════════════════════════════════
# PRÊTS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[6]:
    st.subheader("Prêts en cours — indicatif")
    for p in D['prets']:
        tot = p['nb']*p['ech']+p['cap']
        pct = min(100, round((1-p['cap']/tot)*100)) if tot>0 else 0
        with st.expander(f"**{p['nom']}** — {fmt2(p['cap'])} restant"):
            with st.form(f"edit_pret_{p['id']}"):
                pp1,pp2 = st.columns(2)
                with pp1:
                    pn = st.text_input("Nom", value=p['nom'])
                    pc = st.number_input("Capital restant €", value=float(p['cap']), step=100.0, format="%.2f")
                with pp2:
                    pe = st.number_input("Mensualité €", value=float(p['ech']), step=10.0, format="%.2f")
                    pnb = st.number_input("Mensualités restantes", value=int(p['nb']), step=1)
                st.progress(pct/100, text=f"{pct}% remboursé")
                if st.form_submit_button("💾 Enregistrer", width="stretch"):
                    idx = next(i for i,x in enumerate(D['prets']) if x['id']==p['id'])
                    D['prets'][idx] = {'id':p['id'],'nom':pn,'cap':float(pc),'ech':float(pe),'nb':int(pnb)}
                    persist(); st.success("✓"); st.rerun()
            if st.button("🗑 Supprimer", key=f"del_p_{p['id']}"):
                D['prets'] = [x for x in D['prets'] if x['id']!=p['id']]
                persist(); st.rerun()

    st.divider()
    st.markdown("**Ajouter un prêt**")
    with st.form("add_pret", clear_on_submit=True):
        pp1,pp2 = st.columns(2)
        pnom = pp1.text_input("Nom")
        pcap = pp1.number_input("Capital restant €", min_value=0.0, step=100.0)
        pech = pp2.number_input("Mensualité €", min_value=0.0, step=10.0)
        pnb2 = pp2.number_input("Mensualités restantes", min_value=0, step=1)
        if st.form_submit_button("✅ Enregistrer", width="stretch"):
            D['prets'].append({'id':f"p_{int(datetime.now().timestamp()*1000)}",'nom':pnom,
                               'cap':float(pcap),'ech':float(pech),'nb':int(pnb2)})
            persist(); st.success("✓"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# CATÉGORIES
# ══════════════════════════════════════════════════════════════════════════════
with tabs[7]:
    st.subheader("Catégories")
    st.caption("Les catégories invisibles n'apparaissent plus dans les listes déroulantes mais les transactions existantes sont conservées.")

    vis_count = sum(1 for c in D['cats'] if c.get('visible',True))
    st.info(f"**{vis_count}** visibles sur **{len(D['cats'])}** total")

    changed = False
    for cat in sorted(D['cats'], key=lambda c: c['nom']):
        cc1,cc2,cc3 = st.columns([4,1,1])
        cc1.write(f"{'✅' if cat.get('visible',True) else '🚫'} {cat['nom']}")
        if cc2.button("👁" if not cat.get('visible',True) else "🙈",
                      key=f"vis_{cat['nom']}", help="Rendre visible/invisible"):
            cat['visible'] = not cat.get('visible',True)
            changed = True
    if changed:
        persist(); st.rerun()

    st.divider()
    with st.form("add_cat", clear_on_submit=True):
        new_cat_name = st.text_input("Nouvelle catégorie")
        if st.form_submit_button("Ajouter"):
            if new_cat_name and not any(c['nom']==new_cat_name for c in D['cats']):
                D['cats'].append({'nom':new_cat_name,'visible':True})
                persist(); st.success(f"✓ « {new_cat_name} » ajoutée."); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# SAUVEGARDE
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC PRÉVISION
# ══════════════════════════════════════════════════════════════════════════════
with tabs[8]:
    st.subheader("🔬 Diagnostic — données utilisées par le modèle de prévision")
    st.caption("Vérifie ici exactement ce que le modèle voit pour chaque catégorie avant de prévoir.")

    diag_cpt = st.selectbox("Compte à analyser", ['ca', 'mb'],
                             format_func=lambda x: COMPTES[x]['label'], key="diag_cpt")

    now_d = datetime.now()
    cm_d, cy_d = now_d.month - 1, now_d.year
    CATS_EXCLUES_D = CATS_NEUTRES
    rec_ids_d = {r['id'] for r in D['rec']}

    # Reconstituer l'historique tel que vu par le modèle
    hist_months_d = [month_add(cm_d, cy_d, -i) for i in range(1, 19)]
    hist_months_d.reverse()

    hist_d = defaultdict(list)
    for m_h, y_h in hist_months_d:
        abs_m = y_h * 12 + m_h
        tx_m = [t for t in D['tx']
                if t['compte'] == diag_cpt
                and aff_key(t) == (y_h, m_h)
                and t['type'] == 'depense'
                and not t.get('recId')
                and not t.get('exceptionnel', False)
                and t.get('categorie') not in CATS_EXCLUES_D]
        if diag_cpt == 'ca':
            tx_m += [t for t in D['tx']
                     if t['compte'] == 'mc'
                     and t['type'] == 'depense'
                     and not t.get('recId')
                     and not t.get('exceptionnel', False)
                     and t.get('categorie') not in CATS_EXCLUES_D
                     and aff_key(t) == (y_h, m_h)]
        cat_totals = defaultdict(float)
        for t in tx_m:
            cat_totals[t['categorie']] += t['montant']
        for cat, total in cat_totals.items():
            hist_d[cat].append((f"{MOIS_COURT[m_h]} {y_h}", abs_m, round(total, 2)))

    # ── Revenus utilisés ───────────────────────────────────────────────────
    st.markdown("### Revenus estimés pour les mois futurs")
    rec_rev_d = sum(r['mnt'] for r in D['rec']
                    if r['compte'] == diag_cpt and r['type'] == 'revenu')
    past_rev_raw = []
    for i in range(6):
        pm2, py2 = month_add(cm_d, cy_d, -(i+1))
        tx_rev = [t for t in D['tx']
                  if t['compte'] == diag_cpt
                  and aff_key(t) == (py2, pm2)
                  and t['type'] == 'revenu'
                  and not t.get('recId')
                  and not t.get('exceptionnel', False)
                  and t.get('categorie') not in CATS_NEUTRES]
        if tx_rev:
            total_rev = sum(t['montant'] for t in tx_rev)
            past_rev_raw.append((f"{MOIS_COURT[pm2]} {py2}", round(total_rev, 2)))

    # Filtre IQR sur les revenus variables
    vals_rev_d = [v for _, v in past_rev_raw]
    if len(vals_rev_d) >= 4:
        q1_r, q3_r = np.percentile(vals_rev_d, 25), np.percentile(vals_rev_d, 75)
        iqr_r = q3_r - q1_r
        lo_r, hi_r = q1_r - 1.5*iqr_r, q3_r + 1.5*iqr_r
        past_rev_d = [(lbl, v) for lbl, v in past_rev_raw if lo_r <= v <= hi_r]
        outliers_rev = [(lbl, v) for lbl, v in past_rev_raw if not (lo_r <= v <= hi_r)]
    else:
        past_rev_d = past_rev_raw
        outliers_rev = []

    r1, r2, r3 = st.columns(3)
    r1.metric("Récurrentes revenus (D['rec'])", fmt(rec_rev_d))
    avg_rev_var_d = sum(v for _, v in past_rev_d) / len(past_rev_d) if past_rev_d else 0
    r2.metric("Revenus variables moyens filtrés", fmt(avg_rev_var_d))
    r3.metric("Total rev. estimé / mois", fmt(rec_rev_d + avg_rev_var_d))

    if past_rev_raw:
        df_rev_rows = []
        outlier_labels = {lbl for lbl, _ in outliers_rev}
        for lbl, v in past_rev_raw:
            flag = "⚠️ outlier exclu" if lbl in outlier_labels else "✓ inclus"
            df_rev_rows.append({'Mois': lbl, 'Revenus variables': fmt(v), 'Statut IQR': flag})
        st.dataframe(pd.DataFrame(df_rev_rows).set_index('Mois'), width="stretch")
        if outliers_rev:
            st.caption(f"⚠️ {len(outliers_rev)} mois exclus comme outliers revenus : "
                       + ", ".join(f"{l} ({fmt(v)})" for l, v in outliers_rev))
    else:
        st.warning("Aucun revenu variable détecté (hors virements internes et récurrentes).")

    st.divider()

    # ── Dépenses par catégorie ─────────────────────────────────────────────
    st.markdown("### Dépenses variables par catégorie (après filtre IQR)")

    if not hist_d:
        st.info("Aucune donnée de dépense variable trouvée.")
    else:
        # Récurrentes fixes
        rec_dep_d = sum(r['mnt'] for r in D['rec']
                        if r['compte'] == diag_cpt and r['type'] == 'depense')
        mc_rec_d  = mc_rec_depenses() if diag_cpt == 'ca' else 0
        st.info(f"Récurrentes fixes = **{fmt(rec_dep_d + mc_rec_d)}** / mois "
                f"({'CA: ' + fmt(rec_dep_d) + ' + MC rec: ' + fmt(mc_rec_d) if diag_cpt == 'ca' else fmt(rec_dep_d)})")

        summary_rows = []
        for cat in sorted(hist_d.keys()):
            data_raw = sorted(hist_d[cat], key=lambda x: x[1])
            vals_raw = [v for _, _, v in data_raw]
            n_raw = len(vals_raw)

            # Filtre IQR
            if n_raw >= 4:
                q1, q3 = np.percentile(vals_raw, 25), np.percentile(vals_raw, 75)
                iqr = q3 - q1
                lo, hi = q1 - 1.5*iqr, q3 + 1.5*iqr
                data_ok = [(lbl, a, v) for lbl, a, v in data_raw if lo <= v <= hi]
                outliers = [(lbl, v) for lbl, _, v in data_raw if not (lo <= v <= hi)]
            else:
                data_ok = data_raw
                outliers = []

            vals_ok = [v for _, _, v in data_ok]
            moyenne = round(float(np.mean(vals_ok)), 2) if vals_ok else 0
            summary_rows.append({
                'Catégorie': cat,
                'Mois observés': n_raw,
                'Après IQR': len(data_ok),
                'Outliers exclus': len(outliers),
                'Moyenne estimée': fmt(moyenne),
                'Min obs.': fmt(min(vals_ok)) if vals_ok else "—",
                'Max obs.': fmt(max(vals_ok)) if vals_ok else "—",
                'Outliers (mois, montant)': ", ".join(f"{l}: {fmt(v)}" for l, v in outliers) if outliers else "—"
            })

        df_diag = pd.DataFrame(summary_rows).set_index('Catégorie')
        st.dataframe(df_diag, width="stretch")

        total_var = sum(float(r['Moyenne estimée'].replace(' ','').replace(' €','').replace('—','0')) 
                        for r in summary_rows if r['Moyenne estimée'] != '—')
        st.metric("Total variable estimé / mois", fmt(total_var))
        st.metric("Total dépenses estimées / mois (variable + récurrentes)",
                  fmt(total_var + rec_dep_d + mc_rec_d))
        st.metric("Solde mensuel net estimé",
                  fmt(rec_rev_d + avg_rev_var_d - total_var - rec_dep_d - mc_rec_d))

        st.divider()
        st.markdown("### Détail mensuel par catégorie (données brutes)")
        cat_sel = st.selectbox("Catégorie", sorted(hist_d.keys()), key="diag_cat")
        if cat_sel:
            data_raw2 = sorted(hist_d[cat_sel], key=lambda x: x[1])
            vals_raw2 = [v for _, _, v in data_raw2]
            if len(vals_raw2) >= 4:
                q1, q3 = np.percentile(vals_raw2, 25), np.percentile(vals_raw2, 75)
                iqr = q3 - q1
                lo2, hi2 = q1 - 1.5*iqr, q3 + 1.5*iqr
            else:
                lo2, hi2 = -1, float('inf')
            rows_cat = []
            for lbl, _, v in data_raw2:
                flag = "⚠️ outlier exclu" if not (lo2 <= v <= hi2) else "✓ inclus"
                rows_cat.append({'Mois': lbl, 'Montant': fmt(v), 'Statut IQR': flag})
            st.dataframe(pd.DataFrame(rows_cat).set_index('Mois'), width="stretch")

with tabs[9]:
    st.subheader("💾 Sauvegarde & Restauration")
    bk1,bk2 = st.columns(2)
    with bk1:
        st.markdown("**📥 Exporter**")
        backup = {'version':2,'date':datetime.now().isoformat(),
                  'tx':D['tx'],'cats':D['cats'],'prets':D['prets'],
                  'rec':D['rec'],'sol':D['sol'],'overdraft':D['overdraft']}
        st.download_button("⬇️ Télécharger JSON",
                           data=json.dumps(backup,ensure_ascii=False,indent=2),
                           file_name=f"budget_backup_{datetime.now().strftime('%Y-%m-%d')}.json",
                           mime="application/json", width="stretch")
        st.info(f"**{len(D['tx'])}** transactions · **{len(D['rec'])}** récurrentes · **{len(D['prets'])}** prêts")
    with bk2:
        st.markdown("**📤 Restaurer**")
        st.warning("⚠️ Remplace toutes les données.")
        uploaded = st.file_uploader("Fichier JSON", type=['json'])
        if uploaded:
            try:
                data_in = json.load(uploaded)
                if st.button("🔄 Restaurer", type="primary", width="stretch"):
                    if data_in.get('tx'): D['tx'] = data_in['tx']
                    if data_in.get('cats'):
                        cats_in = data_in['cats']
                        if cats_in and isinstance(cats_in[0], str):
                            cats_in = [{'nom':c,'visible':True} for c in cats_in]
                        D['cats'] = cats_in
                    if data_in.get('prets'): D['prets'] = data_in['prets']
                    if data_in.get('rec'): D['rec'] = data_in['rec']
                    if data_in.get('sol'): D['sol'] = data_in['sol']
                    if data_in.get('overdraft'): D['overdraft'] = data_in['overdraft']
                    persist(); st.success(f"✓ {len(D['tx'])} transactions restaurées !"); st.rerun()
            except Exception as e:
                st.error(f"Erreur : {e}")
    st.divider()
    if D['tx']:
        df_exp = pd.DataFrame([{'Date':t['date'],'Compte':t['compte'],'Catégorie':t['categorie'],
                                 'Type':t['type'],'Montant':t['montant'],'Note':t.get('note','')} for t in D['tx']])
        st.download_button("⬇️ Export CSV", data=df_exp.to_csv(index=False,encoding='utf-8-sig'),
                           file_name="budget.csv", mime="text/csv", width="stretch")
