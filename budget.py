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
        ws.clear()
        ws.update(
            range_name=f"A1:A{len(chunks)}",
            values=[[chunk] for chunk in chunks]
        )
    except Exception as e:
        st.error(f"Erreur de sauvegarde : {e}")

# ── Session state ───────────────────────────────────────────────────────────────
if 'data' not in st.session_state:
    st.session_state.data = load_from_gsheet()
if 'cur_m' not in st.session_state:
    st.session_state.cur_m = datetime.now().month - 1
if 'cur_y' not in st.session_state:
    st.session_state.cur_y = datetime.now().year
if 'fcpt' not in st.session_state:
    st.session_state.fcpt = 'all'

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

# ── Prévisionnel refondu ────────────────────────────────────────────────────────
def resolve_sol(cpt_id, m, y, depth=12):
    """
    Retourne (solde_debut_mois, source) en remontant l'historique si nécessaire.
    source = 'saisi' | 'calculé' | None
    """
    v = get_sol(cpt_id, m, y)
    if v is not None:
        return v, 'saisi'
    if depth <= 0:
        return None, None
    pm, py = month_add(m, y, -1)
    base, src = resolve_sol(cpt_id, pm, py, depth - 1)
    if base is None:
        return None, None
    # Mouvements directs du compte sur le mois pm
    mvt = sum(t['montant'] if t['type'] == 'revenu' else -t['montant']
              for t in D['tx'] if t['compte'] == cpt_id and aff_key(t) == (py, pm))
    # Pour CA : soustraire le cumul MC affecté au mois pm (prélevé en fin de mois)
    if cpt_id == 'ca':
        mc_total = sum(t['montant'] for t in D['tx']
                       if t['compte'] == 'mc' and t['type'] == 'depense'
                       and aff_key(t) == (py, pm))
        mvt -= mc_total
    return base + mvt, 'calculé'


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
        base_sol, src = resolve_sol(cpt_id, start_m, start_y)
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
            if cpt_id == 'ca':
                mc_cumul = sum(
                    t['montant'] for t in D['tx']
                    if t['compte'] == 'mc' and t['type'] == 'depense'
                    and aff_key(t) == (y, m)
                )

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
                    # Ajouter MC récurrentes non encore prélevées ce mois
                    mc_rec = sum(r['mnt'] for r in D['rec']
                                 if r['compte'] == 'mc' and r['type'] == 'depense'
                                 and not rec_applied(r['id'], m, y))
                    mc_cumul += mc_rec

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
        # Moyenne TX non-récurrentes sur les 6 derniers mois passés
        past_nets = []
        for i in range(6):
            pm2, py2 = months[i]
            non_rec = [t for t in D['tx']
                       if t['compte'] == cpt_id
                       and aff_key(t) == (py2, pm2)
                       and not t.get('recId')]
            if non_rec:
                net = sum(t['montant'] if t['type'] == 'revenu' else -t['montant']
                          for t in non_rec)
                past_nets.append(net)
        avg_non_rec = sum(past_nets) / len(past_nets) if past_nets else 0.0

        rec_net = sum(r['mnt'] if r['type'] == 'revenu' else -r['mnt']
                      for r in D['rec'] if r['compte'] == cpt_id)
        mc_rec_monthly = sum(r['mnt'] for r in D['rec']
                             if r['compte'] == 'mc' and r['type'] == 'depense') \
                         if cpt_id == 'ca' else 0.0

        monthly_pts = []
        for idx in range(12):
            m, y = months[idx]
            rel = idx - 6
            label = f"{MOIS_COURT[m]} {y}"

            if rel <= 0:
                # Passé + mois courant : lire depuis courbe journalière
                prefix = f"{y}-{m+1:02d}-"
                pts_m = [(ds, sv) for ds, sv in daily_series[cpt_id] if ds.startswith(prefix)]
                val = pts_m[-1][1] if pts_m else None
                is_fc = False
            else:
                # Futur
                prev_val = monthly_pts[-1][1] if monthly_pts else None
                if prev_val is None:
                    val = None
                else:
                    val = prev_val + rec_net + avg_non_rec - mc_rec_monthly
                is_fc = True

            monthly_pts.append((label, val, is_fc))

        monthly_series[cpt_id] = monthly_pts

    return months, daily_series, monthly_series, warnings_out


# ── CSS ─────────────────────────────────────────────────────────────────────────
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
                "🔄 Récurrentes","📈 Prévisionnel","🏦 Prêts","🏷️ Catégories","💾 Sauvegarde"])

# ══════════════════════════════════════════════════════════════════════════════
# AUJOURD'HUI
# ══════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    now = datetime.now()
    st.subheader(f"Situation au {now.strftime('%d/%m/%Y')}")

    cols = st.columns(3)
    for i, (cpt_id, cpt) in enumerate(COMPTES.items()):
        with cols[i]:
            solde = solde_a_date(cpt_id)
            od = D['overdraft'].get(cpt_id, 0)
            up = upcoming_rec(cpt_id)
            up_net = sum(r['mnt'] if r['type']=='revenu' else -r['mnt'] for r in up)
            proj = solde + up_net if solde is not None else None
            deb = get_sol(cpt_id, now.month-1, now.year)
            status = 'ok'
            if solde is not None and solde < -od: status = 'danger'
            elif (proj is not None and proj < -od) or (solde is not None and solde < (-od+300)): status = 'warn'
            st.markdown(f"""
            <div class="metric-card today-{status}">
                <strong style="font-size:14px">{cpt['label']}</strong><br>
                <small style="color:#888">Solde début de mois</small><br>
                <span style="font-size:13px">{deb if deb is not None else 'Non renseigné'}</span><br><br>
                <small style="color:#888">Solde au {now.day}/{now.month:02d}</small><br>
                <span style="font-size:22px;font-weight:700;color:{'#E24B4A' if (solde or 0)<0 else '#1D9E75'}">{fmt2(solde)}</span><br>
                <small style="color:#888">{'→ ' + fmt2(proj) + ' après prélèvements' if up else 'Aucun prélèvement en attente'}</small><br>
                <small style="color:#888">Découvert autorisé : {fmt2(-od)}</small>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")
    col_al, col_od = st.columns([2,1])
    with col_al:
        st.markdown("**⚠️ Alertes & prélèvements à venir**")
        has_alert = False
        for cpt_id, cpt in COMPTES.items():
            for typ, msg in get_alerts(cpt_id):
                has_alert = True
                st.markdown(f'<div class="alert-{typ}"><strong>{cpt["label"]}</strong> — {msg}</div>', unsafe_allow_html=True)
        if not has_alert:
            st.markdown('<div class="alert-ok">✓ Tous les comptes sont en ordre.</div>', unsafe_allow_html=True)
        all_up = sorted(
            [{'r':r,'cpt':COMPTES[cpt_id]} for cpt_id in COMPTES for r in upcoming_rec(cpt_id)],
            key=lambda x: x['r']['jour']
        )
        if all_up:
            st.markdown("**Prochains prélèvements :**")
            for x in all_up:
                r, cpt = x['r'], x['cpt']
                sign = '−' if r['type']=='depense' else '+'
                st.write(f"• **{cpt['label'].split()[0]}** — {r['nom']} — le {r['jour']} — {sign}{fmt2(r['mnt'])}")
    with col_od:
        st.markdown("**Découverts autorisés**")
        for cpt_id, cpt in COMPTES.items():
            new_od = st.number_input(cpt['label'], value=float(D['overdraft'].get(cpt_id,0)),
                                     step=50.0, key=f"od_{cpt_id}")
            if new_od != D['overdraft'].get(cpt_id,0):
                D['overdraft'][cpt_id] = new_od; persist()

    st.markdown("---")
    st.markdown("**Dernières transactions du mois**")
    tx_now = sorted(tx_of_month(now.month-1, now.year), key=lambda t: t['date'], reverse=True)[:8]
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
    sol_cols = st.columns(3)
    for i, (cpt_id, cpt) in enumerate(COMPTES.items()):
        with sol_cols[i]:
            deb = get_sol(cpt_id, M, Y)
            mvt = sum(t['montant'] if t['type']=='revenu' else -t['montant']
                      for t in tx_of_month(M,Y) if t['compte']==cpt_id)
            fin = (deb+mvt) if deb is not None else None
            with st.expander(f"**{cpt['label']}**", expanded=True):
                c1,c2,c3 = st.columns(3)
                c1.metric("Début", fmt2(deb))
                c2.metric("Mouvement", f"{'+' if mvt>=0 else ''}{fmt2(mvt)}")
                c3.metric("Fin", fmt2(fin))
                new_sol = st.number_input("Solde au 1er :", value=float(deb) if deb is not None else 0.0,
                                          step=10.0, key=f"sol_{cpt_id}_{M}_{Y}", format="%.2f")
                if st.button("💾 Enregistrer", key=f"sav_{cpt_id}_{M}_{Y}"):
                    set_sol(cpt_id, M, Y, new_sol); persist()
                    st.success("✓"); st.rerun()

    st.divider()
    rev = sum(t['montant'] for t in TX_CUR if t['type']=='revenu')
    dep = sum(t['montant'] for t in TX_CUR if t['type']=='depense')
    k1,k2,k3 = st.columns(3)
    k1.metric("Revenus", fmt(rev))
    k2.metric("Dépenses", fmt(dep))
    k3.metric("Variation", f"{'+' if rev-dep>=0 else ''}{fmt(rev-dep)}")
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
    cats_filt = ['Toutes'] + sorted(set(t['categorie'] for t in TX_CUR))
    filt_cat = st.selectbox("Filtrer par catégorie", cats_filt)
    tx_show = sorted(
        TX_CUR if filt_cat=='Toutes' else [t for t in TX_CUR if t['categorie']==filt_cat],
        key=lambda t: t['date'], reverse=True
    )
    if not tx_show:
        st.info("Aucune transaction.")
    else:
        for t in tx_show:
            d = datetime.strptime(t['date'],'%Y-%m-%d')
            cpt = COMPTES.get(t['compte'],{'label':t['compte']})
            with st.expander(f"{'−' if t['type']=='depense' else '+'}{fmt2(t['montant'])} — {t.get('note') or t['categorie']} — {d.strftime('%d/%m/%Y')}", expanded=False):
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
                                        'note': new_note, 'affM': new_affm, 'affY': new_affy}
                        persist(); st.success("✓"); st.rerun()
                if st.button("🗑 Supprimer", key=f"del_tx_{t['id']}"):
                    D['tx'] = [x for x in D['tx'] if x['id']!=t['id']]
                    persist(); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# SAISIE
# ══════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.subheader("Ajouter une transaction")
    with st.form("add_tx", clear_on_submit=True):
        fc1,fc2 = st.columns(2)
        with fc1:
            tx_date = st.date_input("Date (JJ/MM/AAAA)", value=date.today(), format="DD/MM/YYYY")
            tx_cpt = st.selectbox("Compte", list(COMPTES.keys()), format_func=lambda x: COMPTES[x]['label'])
            tx_type = st.radio("Type", ['depense','revenu'],
                               format_func=lambda x: '💸 Dépense' if x=='depense' else '💰 Revenu',
                               horizontal=True)
        with fc2:
            tx_cat = st.selectbox("Catégorie", visible_cats())
            tx_mnt = st.number_input("Montant (€)", min_value=0.01, step=0.01, format="%.2f")
            tx_note = st.text_input("Note", placeholder="Description…")
        aff_m = aff_y = None
        if tx_cpt == 'mc':
            st.info("💳 **Mastercard débit différé** — mois d'affectation :")
            m1,m2 = st.columns(2)
            aff_m = m1.selectbox("Mois", range(12), index=datetime.now().month-1, format_func=lambda x: MOIS[x])
            aff_y = m2.selectbox("Année", [2024,2025,2026,2027], index=2)
        if st.form_submit_button("✅ Ajouter", type="primary", width="stretch"):
            new_tx = {'id':f"tx_{int(datetime.now().timestamp()*1000)}",
                      'date':tx_date.strftime('%Y-%m-%d'), 'compte':tx_cpt,
                      'categorie':tx_cat, 'montant':float(tx_mnt),
                      'type':tx_type, 'note':tx_note}
            if tx_cpt=='mc' and aff_m is not None:
                new_tx['affM'] = aff_m; new_tx['affY'] = aff_y
            D['tx'].append(new_tx); persist()
            st.success(f"✓ {fmt2(tx_mnt)} — {tx_cat}"); st.rerun()

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
    for r in D['rec']:
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
# PRÉVISIONNEL — refondu
# ══════════════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.subheader("Prévisionnel — CA & Monabanq")
    st.caption(
        "**Passé** : courbe journalière réelle · MC cumulée soustraite fin de mois d'affectation sur CA  |  "
        "**Futur** : solde fin de mois estimé (récurrentes + moyenne TX passées)"
    )

    months, daily_series, monthly_series, fc_warnings = build_forecast_v2()

    for w in fc_warnings:
        st.warning(w)

    now_str = datetime.now().strftime('%Y-%m-%d')
    now_label = datetime.now().strftime('%d/%m/%Y')

    fig = go.Figure()

    # Zone rouge sous 0
    all_vals = [v for s in monthly_series.values() for _, v, _ in s if v is not None]
    y_min = min(all_vals) * 1.15 if all_vals else -1000

    fig.add_hrect(y0=y_min, y1=0, fillcolor="rgba(220,50,50,0.04)", line_width=0)

    for cpt_id in ['ca', 'mb']:
        cpt = COMPTES[cpt_id]
        color = cpt['color']
        r_int = int(color[1:3], 16)
        g_int = int(color[3:5], 16)
        b_int = int(color[5:7], 16)

        # ── Courbe journalière passé ────────────────────────────────────────
        daily_pts = daily_series[cpt_id]
        if daily_pts:
            dates_past = [dp[0] for dp in daily_pts if dp[0] <= now_str]
            vals_past  = [dp[1] for dp in daily_pts if dp[0] <= now_str]
            if dates_past:
                fig.add_trace(go.Scatter(
                    x=dates_past, y=vals_past,
                    mode='lines',
                    name=cpt['label'],
                    line=dict(color=color, width=2),
                    fill='tozeroy',
                    fillcolor=f"rgba({r_int},{g_int},{b_int},0.07)",
                    hovertemplate='%{x}<br>%{y:,.0f} €<extra>' + cpt['label'] + '</extra>'
                ))

            # Projection mois courant (pointillé léger)
            dates_proj = [dp[0] for dp in daily_pts if dp[0] >= now_str]
            vals_proj  = [dp[1] for dp in daily_pts if dp[0] >= now_str]
            if dates_proj:
                fig.add_trace(go.Scatter(
                    x=dates_proj, y=vals_proj,
                    mode='lines',
                    name=f"{cpt['label']} (projection mois courant)",
                    showlegend=False,
                    line=dict(color=color, width=1.5, dash='dot'),
                    hovertemplate='%{x}<br>%{y:,.0f} €<extra>Projection</extra>'
                ))

        # ── Points mensuels futurs ──────────────────────────────────────────
        fc_pts = [(label, val) for label, val, is_fc in monthly_series[cpt_id] if is_fc and val is not None]
        # Ajouter le dernier point réel comme ancrage
        real_pts = [(label, val) for label, val, is_fc in monthly_series[cpt_id] if not is_fc and val is not None]
        anchor = [real_pts[-1]] if real_pts else []
        fc_with_anchor = anchor + fc_pts
        if len(fc_with_anchor) > 1:
            fig.add_trace(go.Scatter(
                x=[p[0] for p in fc_with_anchor],
                y=[p[1] for p in fc_with_anchor],
                mode='lines+markers',
                name=f"{cpt['label']} (prévisionnel)",
                showlegend=False,
                line=dict(color=color, width=1.5, dash='dot'),
                marker=dict(size=7, symbol='circle-open'),
                hovertemplate='%{x}<br>%{y:,.0f} €<extra>Prévisionnel</extra>'
            ))

        # Ligne découvert
        od_val = D['overdraft'].get(cpt_id, 0)
        if od_val > 0:
            fig.add_hline(
                y=-od_val,
                line_dash="dash", line_color=color, line_width=1, opacity=0.5,
                annotation_text=f"Découvert {cpt['label'].split()[0]}",
                annotation_position="bottom right"
            )

    # Ligne verticale aujourd'hui
    fig.add_vline(
        x=now_str,
        line_dash="dot", line_color="gray", line_width=1.5,
        annotation_text=f"Aujourd'hui", annotation_position="top right"
    )

    fig.update_layout(
        height=430,
        hovermode='x unified',
        margin=dict(t=40, b=60, l=60, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
        yaxis_title="Solde (€)",
        xaxis_title="",
    )
    st.plotly_chart(fig, width="stretch")

    # ── Tableau récapitulatif ───────────────────────────────────────────────
    st.markdown("**Tableau mensuel**")
    table_rows = {}
    for cpt_id in ['ca', 'mb']:
        label_cpt = COMPTES[cpt_id]['label'].split()[0]
        table_rows[label_cpt] = []
        for lbl, val, is_fc in monthly_series[cpt_id]:
            prefix = "~" if is_fc else ""
            cell = f"{prefix}{round(val):,} €".replace(",", "\u202f") if val is not None else "—"
            table_rows[label_cpt].append(cell)

    col_labels = [lbl for lbl, _, _ in monthly_series['ca']]
    df_fc = pd.DataFrame(table_rows, index=col_labels)
    st.dataframe(df_fc, width="stretch")

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
with tabs[8]:
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
