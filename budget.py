"""
Budget Familial AS — Application Streamlit
Comptes : Crédit Agricole (CA) · Mastercard débit différé (MC) · Monabanq (MB)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
import os
from datetime import datetime, date
from pathlib import Path
from collections import defaultdict

# ── Config page ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Budget Familial",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Constantes ─────────────────────────────────────────────────────────────────
MOIS = ['Janvier','Février','Mars','Avril','Mai','Juin',
        'Juillet','Août','Septembre','Octobre','Novembre','Décembre']
COMPTES = {
    'ca':  {'label':'Crédit Agricole', 'color':'#378ADD', 'bg':'#E6F1FB', 'tc':'#0C447C'},
    'mc':  {'label':'Mastercard',      'color':'#BA7517', 'bg':'#FAEEDA', 'tc':'#633806'},
    'mb':  {'label':'Monabanq',        'color':'#1D9E75', 'bg':'#E1F5EE', 'tc':'#085041'},
}
CATS_DEFAULT = [
    'ARE / Salaire','Allocations','Revenu freelance','Prêt / Assurance',
    'Frais divers','Nourriture','Habit / Beauté','Santé','Sénégal',
    'CLAE / École','Loisirs / Vacances','Voiture','Abonnement','Tontine',
    'Épargne','Virement interne','Impôts / Taxes','Divers'
]
DATA_FILE = Path("data/budget_data.json")
CC = ['#378ADD','#1D9E75','#D85A30','#D4537E','#7F77DD',
      '#639922','#BA7517','#E24B4A','#888780','#0F6E56']

# ── Helpers format ──────────────────────────────────────────────────────────────
def fmt(n):
    if n is None: return "—"
    return f"{n:,.0f} €".replace(",", " ")

def fmt2(n):
    if n is None: return "—"
    return f"{n:,.2f} €".replace(",", " ")

def aff_key(t):
    """Clé mois d'affectation d'une transaction (gestion MC débit différé)."""
    if t.get('compte') == 'mc' and t.get('affM') is not None and t.get('affY') is not None:
        return (int(t['affY']), int(t['affM']))
    d = datetime.strptime(t['date'], '%Y-%m-%d')
    return (d.year, d.month - 1)  # 0-indexed month

def month_add(m, y, n):
    """Ajoute n mois à (m, y), retourne (new_m, new_y). m est 0-indexed."""
    total = y * 12 + m + n
    return total % 12, total // 12

# ── Stockage données ────────────────────────────────────────────────────────────
def load_data():
    """Charge les données depuis le fichier JSON local."""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        'tx': [], 'cats': CATS_DEFAULT,
        'prets': [], 'rec': [], 'sol': {},
        'overdraft': {'ca': 500, 'mc': 0, 'mb': 250}
    }

def save_data(data):
    """Sauvegarde les données dans le fichier JSON local."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── Session state ───────────────────────────────────────────────────────────────
if 'data' not in st.session_state:
    st.session_state.data = load_data()
if 'cur_m' not in st.session_state:
    st.session_state.cur_m = datetime.now().month - 1  # 0-indexed
if 'cur_y' not in st.session_state:
    st.session_state.cur_y = datetime.now().year
if 'fcpt' not in st.session_state:
    st.session_state.fcpt = 'all'
if 'edit_tx' not in st.session_state:
    st.session_state.edit_tx = None

D = st.session_state.data  # raccourci

def persist():
    save_data(st.session_state.data)

# ── Calculs ─────────────────────────────────────────────────────────────────────
def tx_of_month(m, y, tx=None):
    if tx is None:
        tx = D['tx']
    return [t for t in tx if aff_key(t) == (y, m)]

def rec_applied(rid, m, y):
    return any(t.get('recId') == rid and aff_key(t) == (y, m) for t in D['tx'])

def get_sol(c, m, y):
    k = f"{c}_{y}_{m}"
    v = D['sol'].get(k)
    return float(v) if v is not None else None

def set_sol(c, m, y, v):
    k = f"{c}_{y}_{m}"
    if v is not None:
        D['sol'][k] = v
    else:
        D['sol'].pop(k, None)

def solde_a_date(cpt_id):
    now = datetime.now()
    m, y = now.month - 1, now.year
    deb = get_sol(cpt_id, m, y)
    if deb is None:
        return None
    txs = [t for t in D['tx'] if t['compte'] == cpt_id
           and aff_key(t) == (y, m)
           and datetime.strptime(t['date'], '%Y-%m-%d') <= now]
    mvt = sum(t['montant'] if t['type'] == 'revenu' else -t['montant'] for t in txs)
    return deb + mvt

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
    alerts = []
    if solde is None:
        return []
    if solde < -od:
        alerts.append(('danger', f"Solde dans le rouge : {fmt2(solde)}"))
    elif solde < (-od + 300):
        alerts.append(('warn', f"Solde proche de la limite : {fmt2(solde)}"))
    proj = solde
    for r in upcoming_rec(cpt_id):
        prev = proj
        proj += r['mnt'] if r['type'] == 'revenu' else -r['mnt']
        if proj < -od and prev >= -od:
            alerts.append(('warn', f"« {r['nom']} » ({fmt2(r['mnt'])}) le {r['jour']} → solde prévu {fmt2(proj)}"))
    return alerts

def month_net_actual(cpt_id, m, y):
    return sum(
        t['montant'] if t['type'] == 'revenu' else -t['montant']
        for t in tx_of_month(m, y)
        if t['compte'] == cpt_id
    )

def avg_non_rec(cpt_id):
    now = datetime.now()
    cm, cy = now.month - 1, now.year
    totals = []
    for i in range(1, 7):
        pm, py = month_add(cm, cy, -i)
        txs = [t for t in tx_of_month(pm, py) if t['compte'] == cpt_id and not t.get('recId')]
        if txs:
            totals.append(sum(t['montant'] if t['type'] == 'revenu' else -t['montant'] for t in txs))
    return sum(totals) / len(totals) if totals else 0

def rec_net(cpt_id):
    return sum(r['mnt'] if r['type'] == 'revenu' else -r['mnt'] for r in D['rec'] if r['compte'] == cpt_id)

def build_forecast():
    """Construit les séries de solde prévisionnel sur 12 mois glissants."""
    now = datetime.now()
    cm, cy = now.month - 1, now.year
    months = [month_add(cm, cy, i) for i in range(-6, 6)]  # (m, y) tuples
    series = {}
    for cpt_id in COMPTES:
        base = get_sol(cpt_id, cm, cy) or 0
        nets = []
        for i, (m, y) in enumerate(months):
            rel = i - 6
            if rel < 0:
                nets.append(month_net_actual(cpt_id, m, y))
            elif rel == 0:
                actual = month_net_actual(cpt_id, m, y)
                proj = sum(
                    r['mnt'] if r['type'] == 'revenu' else -r['mnt']
                    for r in D['rec']
                    if r['compte'] == cpt_id and r['jour'] > now.day and not rec_applied(r['id'], m, y)
                )
                nets.append(actual + proj)
            else:
                nets.append(rec_net(cpt_id) + avg_non_rec(cpt_id))
        opens = [0.0] * 12
        opens[6] = base
        for i in range(7, 12):
            opens[i] = opens[i-1] + nets[i-1]
        for j in range(4, -1, -1):
            opens[j] = opens[j+1] - nets[j]
        closes = [opens[i] + nets[i] for i in range(12)]
        series[cpt_id] = {'opens': opens, 'closes': closes, 'nets': nets}
    return months, series

# ── CSS custom ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.main > div { padding-top: 1rem; }
.stTabs [data-baseweb="tab-list"] { gap: 4px; }
.stTabs [data-baseweb="tab"] { padding: 8px 16px; font-size: 13px; }
.metric-card {
    background: var(--background-color);
    border: 1px solid #e0e0e0;
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 8px;
}
.today-ok { border-left: 4px solid #1D9E75; }
.today-warn { border-left: 4px solid #D97706; }
.today-danger { border-left: 4px solid #E24B4A; }
.alert-danger { background: #fdf0f0; border-left: 4px solid #E24B4A; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px; color: #791F1F; font-size: 13px; }
.alert-warn { background: #fff8e6; border-left: 4px solid #D97706; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px; color: #7C4A00; font-size: 13px; }
.alert-ok { background: #f0faf4; border-left: 4px solid #1D9E75; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px; color: #085041; font-size: 13px; }
div[data-testid="stMetric"] { background: #f8f9fa; border-radius: 8px; padding: 10px 14px; }
</style>
""", unsafe_allow_html=True)

# ── NAVIGATION ──────────────────────────────────────────────────────────────────
col_nav1, col_nav2, col_nav3, col_nav4, col_nav5 = st.columns([1,2,1,3,2])
with col_nav1:
    if st.button("◀", use_container_width=True):
        if st.session_state.cur_m == 0:
            st.session_state.cur_m = 11
            st.session_state.cur_y -= 1
        else:
            st.session_state.cur_m -= 1
        st.rerun()
with col_nav2:
    m_options = list(range(12))
    new_m = st.selectbox("", m_options, index=st.session_state.cur_m,
                         format_func=lambda x: MOIS[x], label_visibility='collapsed')
    if new_m != st.session_state.cur_m:
        st.session_state.cur_m = new_m
        st.rerun()
with col_nav3:
    if st.button("▶", use_container_width=True):
        if st.session_state.cur_m == 11:
            st.session_state.cur_m = 0
            st.session_state.cur_y += 1
        else:
            st.session_state.cur_m += 1
        st.rerun()
with col_nav4:
    new_y = st.selectbox("", list(range(2023, 2031)), index=list(range(2023, 2031)).index(st.session_state.cur_y),
                         label_visibility='collapsed')
    if new_y != st.session_state.cur_y:
        st.session_state.cur_y = new_y
        st.rerun()
with col_nav5:
    fcpt_opts = {'all': 'Tous les comptes', **{k: v['label'] for k, v in COMPTES.items()}}
    new_fcpt = st.selectbox("", list(fcpt_opts.keys()), format_func=lambda x: fcpt_opts[x], label_visibility='collapsed')
    if new_fcpt != st.session_state.fcpt:
        st.session_state.fcpt = new_fcpt
        st.rerun()

M, Y = st.session_state.cur_m, st.session_state.cur_y
FCPT = st.session_state.fcpt
TX_CUR = [t for t in tx_of_month(M, Y) if FCPT == 'all' or t['compte'] == FCPT]

st.divider()

# ── ONGLETS ─────────────────────────────────────────────────────────────────────
tabs = st.tabs(["📍 Aujourd'hui", "📊 Mois", "📋 Transactions", "✏️ Saisie",
                "🔄 Récurrentes", "📈 Prévisionnel", "🏦 Prêts",
                "🏷️ Catégories", "💾 Sauvegarde"])

# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 1 — AUJOURD'HUI
# ══════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    now = datetime.now()
    st.subheader(f"Situation au {now.strftime('%d/%m/%Y')}")

    # Cartes par compte
    cols = st.columns(3)
    for i, (cpt_id, cpt) in enumerate(COMPTES.items()):
        with cols[i]:
            solde = solde_a_date(cpt_id)
            od = D['overdraft'].get(cpt_id, 0)
            up = upcoming_rec(cpt_id)
            up_net = sum(r['mnt'] if r['type'] == 'revenu' else -r['mnt'] for r in up)
            proj = solde + up_net if solde is not None else None
            deb = get_sol(cpt_id, now.month - 1, now.year)

            status = 'ok'
            if solde is not None and solde < -od:
                status = 'danger'
            elif (proj is not None and proj < -od) or (solde is not None and solde < (-od + 300)):
                status = 'warn'

            css_class = f"metric-card today-{status}"
            solde_str = fmt2(solde) if solde is not None else "—"
            deb_str = fmt2(deb) if deb is not None else "Non renseigné"
            proj_str = fmt2(proj) if proj is not None else "—"

            st.markdown(f"""
            <div class="{css_class}">
                <strong style="font-size:14px">{cpt['label']}</strong><br>
                <small style="color:#888">Solde début de mois</small><br>
                <span style="font-size:13px">{deb_str}</span><br><br>
                <small style="color:#888">Solde au {now.day}/{now.month:02d}</small><br>
                <span style="font-size:22px;font-weight:700;color:{'#E24B4A' if (solde or 0)<0 else '#1D9E75'}">{solde_str}</span><br>
                <small style="color:#888">{'→ ' + fmt2(proj) + ' après prélèvements' if up else 'Aucun prélèvement en attente'}</small><br>
                <small style="color:#888">Découvert autorisé : {fmt2(-od)}</small>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    col_al, col_od = st.columns([2, 1])

    with col_al:
        st.markdown("**⚠️ Alertes & prélèvements à venir**")
        has_alert = False
        for cpt_id, cpt in COMPTES.items():
            for typ, msg in get_alerts(cpt_id):
                has_alert = True
                st.markdown(f'<div class="alert-{typ}"><strong>{cpt["label"]}</strong> — {msg}</div>', unsafe_allow_html=True)

        if not has_alert:
            st.markdown('<div class="alert-ok">✓ Tous les comptes sont en ordre.</div>', unsafe_allow_html=True)

        # Prélèvements à venir ce mois
        all_up = []
        for cpt_id, cpt in COMPTES.items():
            for r in upcoming_rec(cpt_id):
                all_up.append({**r, 'cpt_label': cpt['label'], 'cpt_color': cpt['color']})
        all_up.sort(key=lambda x: x['jour'])

        if all_up:
            st.markdown("**Prochains prélèvements ce mois :**")
            df_up = pd.DataFrame([{
                'Compte': r['cpt_label'],
                'Nom': r['nom'],
                'Le': r['jour'],
                'Montant': f"{'−' if r['type']=='depense' else '+'}{fmt2(r['mnt'])}"
            } for r in all_up])
            st.dataframe(df_up, use_container_width=True, hide_index=True)

    with col_od:
        st.markdown("**Découverts autorisés**")
        for cpt_id, cpt in COMPTES.items():
            new_od = st.number_input(cpt['label'], value=float(D['overdraft'].get(cpt_id, 0)),
                                     step=50.0, key=f"od_{cpt_id}")
            if new_od != D['overdraft'].get(cpt_id, 0):
                D['overdraft'][cpt_id] = new_od
                persist()

    # Dernières transactions du mois
    st.markdown("---")
    st.markdown("**Dernières transactions du mois**")
    tx_today = sorted(tx_of_month(now.month - 1, now.year), key=lambda t: t['date'], reverse=True)[:8]
    if tx_today:
        df_today = pd.DataFrame([{
            'Date': t['date'][8:] + '/' + t['date'][5:7],
            'Compte': COMPTES[t['compte']]['label'].split()[0],
            'Description': t.get('note') or t['categorie'],
            'Catégorie': t['categorie'],
            'Montant': f"{'−' if t['type']=='depense' else '+'}{fmt2(t['montant'])}"
        } for t in tx_today])
        st.dataframe(df_today, use_container_width=True, hide_index=True)
    else:
        st.info("Aucune transaction ce mois.")


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 2 — MOIS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.subheader(f"{MOIS[M]} {Y}")

    # Soldes par compte
    st.markdown("**Soldes**")
    sol_cols = st.columns(3)
    for i, (cpt_id, cpt) in enumerate(COMPTES.items()):
        with sol_cols[i]:
            deb = get_sol(cpt_id, M, Y)
            mvt = sum(t['montant'] if t['type']=='revenu' else -t['montant']
                      for t in tx_of_month(M, Y) if t['compte'] == cpt_id)
            fin = (deb + mvt) if deb is not None else None
            with st.expander(f"**{cpt['label']}**", expanded=True):
                st.metric("Solde début", fmt2(deb) if deb is not None else "—")
                st.metric("Mouvements", f"{'+' if mvt>=0 else ''}{fmt2(mvt)}", delta=None)
                st.metric("Solde fin", fmt2(fin) if fin is not None else "—")
                new_sol = st.number_input("Solde au 1er :", value=float(deb) if deb is not None else 0.0,
                                          step=10.0, key=f"sol_{cpt_id}_{M}_{Y}")
                if st.button("Enregistrer", key=f"sav_sol_{cpt_id}_{M}_{Y}"):
                    set_sol(cpt_id, M, Y, new_sol)
                    persist()
                    st.success("✓")
                    st.rerun()

    st.divider()

    # KPIs
    rev = sum(t['montant'] for t in TX_CUR if t['type'] == 'revenu')
    dep = sum(t['montant'] for t in TX_CUR if t['type'] == 'depense')
    k1, k2, k3 = st.columns(3)
    k1.metric("Revenus", fmt(rev))
    k2.metric("Dépenses", fmt(dep))
    k3.metric("Variation", f"{'+' if rev-dep>=0 else ''}{fmt(rev-dep)}")

    st.divider()

    # Graphiques
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Dépenses par catégorie**")
        dep_by_cat = defaultdict(float)
        for t in TX_CUR:
            if t['type'] == 'depense':
                dep_by_cat[t['categorie']] += t['montant']
        if dep_by_cat:
            df_cat = pd.DataFrame(sorted(dep_by_cat.items(), key=lambda x: -x[1])[:8],
                                  columns=['Catégorie', 'Montant'])
            fig = go.Figure(go.Bar(
                x=df_cat['Catégorie'], y=df_cat['Montant'],
                marker_color=CC[:len(df_cat)],
                text=[fmt(v) for v in df_cat['Montant']],
                textposition='outside'
            ))
            fig.update_layout(height=300, margin=dict(t=20,b=80), showlegend=False,
                              yaxis_title="€", xaxis_tickangle=-30)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Aucune dépense ce mois.")

    with g2:
        st.markdown("**Répartition par compte**")
        dep_by_cpt = {cpt_id: sum(t['montant'] for t in TX_CUR if t['type']=='depense' and t['compte']==cpt_id)
                      for cpt_id in COMPTES}
        dep_by_cpt = {k: v for k, v in dep_by_cpt.items() if v > 0}
        if dep_by_cpt:
            fig2 = go.Figure(go.Pie(
                labels=[COMPTES[k]['label'] for k in dep_by_cpt],
                values=list(dep_by_cpt.values()),
                marker_colors=[COMPTES[k]['color'] for k in dep_by_cpt],
                hole=0.4
            ))
            fig2.update_layout(height=300, margin=dict(t=20,b=20))
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Aucune dépense ce mois.")


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 3 — TRANSACTIONS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.subheader(f"Transactions — {MOIS[M]} {Y}")

    # Filtre catégorie
    all_cats_cur = sorted(set(t['categorie'] for t in TX_CUR))
    filt_cat = st.selectbox("Filtrer par catégorie", ['Toutes'] + all_cats_cur)
    tx_show = TX_CUR if filt_cat == 'Toutes' else [t for t in TX_CUR if t['categorie'] == filt_cat]
    tx_show = sorted(tx_show, key=lambda t: t['date'], reverse=True)

    if not tx_show:
        st.info("Aucune transaction.")
    else:
        for t in tx_show:
            col_d, col_c, col_n, col_m, col_btn = st.columns([1, 1.2, 2, 1.2, 1])
            d = datetime.strptime(t['date'], '%Y-%m-%d')
            col_d.write(d.strftime('%d/%m'))
            cpt = COMPTES.get(t['compte'], {'label': t['compte']})
            mc_info = f" → {['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc'][int(t['affM'])]}" if t['compte'] == 'mc' and t.get('affM') is not None else ""
            col_c.write(f"**{cpt['label'].split()[0]}**{mc_info}")
            rec_icon = " ↺" if t.get('recId') else ""
            col_n.write(f"{t.get('note') or t['categorie']}{rec_icon}")
            color = "🔴" if t['type'] == 'depense' else "🟢"
            sign = "−" if t['type'] == 'depense' else "+"
            col_m.write(f"{color} {sign}{fmt2(t['montant'])}")
            with col_btn:
                if st.button("🗑", key=f"del_{t['id']}"):
                    D['tx'] = [x for x in D['tx'] if x['id'] != t['id']]
                    persist()
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 4 — SAISIE
# ══════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.subheader("Ajouter une transaction")
    with st.form("add_tx_form", clear_on_submit=True):
        fc1, fc2 = st.columns(2)
        with fc1:
            tx_date = st.date_input("Date", value=date.today())
            tx_cpt = st.selectbox("Compte", list(COMPTES.keys()),
                                  format_func=lambda x: COMPTES[x]['label'])
            tx_type = st.radio("Type", ['depense', 'revenu'],
                               format_func=lambda x: '💸 Dépense' if x == 'depense' else '💰 Revenu',
                               horizontal=True)
        with fc2:
            tx_cat = st.selectbox("Catégorie", D['cats'])
            tx_mnt = st.number_input("Montant (€)", min_value=0.01, step=0.01, format="%.2f")
            tx_note = st.text_input("Note (optionnel)", placeholder="Description libre…")

        # Mastercard : mois d'affectation
        aff_m, aff_y = None, None
        if tx_cpt == 'mc':
            st.info("💳 **Mastercard débit différé** — Le mois d'affectation peut différer de la date réelle.")
            mc1, mc2 = st.columns(2)
            with mc1:
                aff_m = st.selectbox("Mois d'affectation", range(12), index=datetime.now().month - 1,
                                     format_func=lambda x: MOIS[x])
            with mc2:
                aff_y = st.selectbox("Année", [2024, 2025, 2026, 2027], index=2)

        submitted = st.form_submit_button("✅ Ajouter la transaction", type="primary", use_container_width=True)
        if submitted:
            if tx_mnt <= 0:
                st.error("Le montant doit être supérieur à 0.")
            else:
                new_tx = {
                    'id': f"tx_{int(datetime.now().timestamp()*1000)}",
                    'date': tx_date.strftime('%Y-%m-%d'),
                    'compte': tx_cpt,
                    'categorie': tx_cat,
                    'montant': float(tx_mnt),
                    'type': tx_type,
                    'note': tx_note
                }
                if tx_cpt == 'mc' and aff_m is not None:
                    new_tx['affM'] = aff_m
                    new_tx['affY'] = aff_y
                D['tx'].append(new_tx)
                persist()
                st.success(f"✓ Transaction ajoutée : {fmt2(tx_mnt)} — {tx_cat}")
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 5 — RÉCURRENTES
# ══════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.subheader(f"Charges récurrentes — {MOIS[M]} {Y}")

    applied_count = sum(1 for r in D['rec'] if rec_applied(r['id'], M, Y))
    st.info(f"**{applied_count} / {len(D['rec'])}** charges appliquées ce mois.")

    if st.button("⚡ Appliquer toutes les récurrentes au mois en cours", type="primary"):
        added = 0
        for r in D['rec']:
            if rec_applied(r['id'], M, Y):
                continue
            j = min(r['jour'], 28)
            ds = f"{Y}-{M+1:02d}-{j:02d}"
            D['tx'].append({
                'id': f"tx_{int(datetime.now().timestamp()*1000)}_{added}",
                'date': ds, 'compte': r['compte'], 'categorie': r['cat'],
                'montant': r['mnt'], 'type': r['type'], 'note': r['nom'], 'recId': r['id']
            })
            added += 1
        persist()
        st.success(f"✓ {added} charge(s) appliquée(s) pour {MOIS[M]} {Y}.")
        st.rerun()

    st.divider()

    # Liste des récurrentes
    if D['rec']:
        for r in D['rec']:
            done = rec_applied(r['id'], M, Y)
            icon = "✅" if done else "⏳"
            cpt = COMPTES.get(r['compte'], {'label': r['compte']})
            sign = "−" if r['type'] == 'depense' else "+"
            rc1, rc2, rc3, rc4, rc5, rc6 = st.columns([2, 1.2, 1.5, 1, 0.8, 0.6])
            rc1.write(f"{icon} **{r['nom']}** (j.{r['jour']})")
            rc2.write(cpt['label'].split()[0])
            rc3.write(r['cat'])
            rc4.write(f"{sign}{fmt2(r['mnt'])}")
            rc5.write("✓" if done else "—")
            with rc6:
                if st.button("🗑", key=f"del_rec_{r['id']}"):
                    D['rec'] = [x for x in D['rec'] if x['id'] != r['id']]
                    persist()
                    st.rerun()
    else:
        st.info("Aucune charge récurrente enregistrée. Restaure ton JSON de sauvegarde.")

    st.divider()
    st.markdown("**Ajouter une charge récurrente**")
    with st.form("add_rec_form", clear_on_submit=True):
        ar1, ar2 = st.columns(2)
        with ar1:
            r_nom = st.text_input("Nom", placeholder="Loyer, SFR, Netflix…")
            r_cpt = st.selectbox("Compte", list(COMPTES.keys()), format_func=lambda x: COMPTES[x]['label'])
            r_type = st.radio("Type", ['depense', 'revenu'],
                              format_func=lambda x: '💸 Dépense' if x == 'depense' else '💰 Revenu',
                              horizontal=True, key="rtype")
        with ar2:
            r_cat = st.selectbox("Catégorie", D['cats'], key="rcat")
            r_mnt = st.number_input("Montant (€)", min_value=0.01, step=0.01, format="%.2f", key="rmnt")
            r_jour = st.number_input("Jour du mois", min_value=1, max_value=28, value=5)
        if st.form_submit_button("✅ Enregistrer", use_container_width=True):
            D['rec'].append({
                'id': f"r_{int(datetime.now().timestamp()*1000)}",
                'nom': r_nom, 'compte': r_cpt, 'cat': r_cat,
                'mnt': float(r_mnt), 'type': r_type, 'jour': int(r_jour)
            })
            persist()
            st.success("✓ Charge enregistrée !")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 6 — PRÉVISIONNEL
# ══════════════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.subheader("Prévisionnel 12 mois glissants")
    st.caption("Trait plein = réel · Pointillé = prévisionnel (récurrentes + moyenne) · Ligne tiretée = limite découvert")

    months, series = build_forecast()
    month_labels = [f"{'~' if i>6 else ''}{['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc'][m]}\n{y}" for i,(m,y) in enumerate(months)]

    fig = go.Figure()

    # Zone rouge (négatif)
    y_min_all = min(min(s['closes']) for s in series.values())
    fig.add_hrect(y0=y_min_all * 1.1, y1=0, fillcolor="rgba(220,50,50,0.05)", line_width=0)

    for cpt_id, cpt in COMPTES.items():
        closes = series[cpt_id]['closes']
        now_idx = 6

        # Ligne passé (pleine)
        fig.add_trace(go.Scatter(
            x=month_labels[:now_idx+1], y=closes[:now_idx+1],
            mode='lines+markers', name=cpt['label'],
            line=dict(color=cpt['color'], width=2),
            marker=dict(size=6, color=[
                '#E24B4A' if (cpt_id != 'mc' and v < -(D['overdraft'].get(cpt_id, 0))) else cpt['color']
                for v in closes[:now_idx+1]
            ]),
            fill='tozeroy', fillcolor=f"rgba({int(cpt['color'][1:3],16)},{int(cpt['color'][3:5],16)},{int(cpt['color'][5:7],16)},0.05)"
        ))
        # Ligne futur (pointillée)
        if now_idx < 11:
            fig.add_trace(go.Scatter(
                x=month_labels[now_idx:], y=closes[now_idx:],
                mode='lines+markers', showlegend=False,
                line=dict(color=cpt['color'], width=1.5, dash='dot'),
                marker=dict(size=5, color=cpt['color'])
            ))
        # Ligne découvert
        od_val = D['overdraft'].get(cpt_id, 0)
        if od_val > 0 and cpt_id != 'mc':
            fig.add_hline(y=-od_val, line_dash="dash", line_color=cpt['color'],
                          line_width=1, opacity=0.4,
                          annotation_text=f"-{od_val}€", annotation_position="right")

    # Ligne Aujourd'hui
    fig.add_vline(x=month_labels[6], line_dash="dot", line_color="gray", line_width=1.5)
    fig.add_annotation(x=month_labels[6], y=1, yref="paper", text="Aujourd'hui",
                       showarrow=False, font=dict(size=10, color="gray"), yanchor="bottom")

    fig.update_layout(
        height=400, hovermode='x unified',
        margin=dict(t=40, b=60, l=60, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
        yaxis_title="Solde (€)", xaxis_title=""
    )
    st.plotly_chart(fig, use_container_width=True)

    # Tableau récap
    st.markdown("**Tableau récapitulatif**")
    df_fc = pd.DataFrame(
        {cpt['label'].split()[0]: [f"{'~' if i>6 else ''}{round(series[cpt_id]['closes'][i])}" for i in range(12)]
         for cpt_id, cpt in COMPTES.items()},
        index=month_labels
    )
    st.dataframe(df_fc, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 7 — PRÊTS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[6]:
    st.subheader("Prêts en cours — indicatif")

    if D['prets']:
        for p in D['prets']:
            tot = p['nb'] * p['ech'] + p['cap']
            pct = min(100, round((1 - p['cap'] / tot) * 100)) if tot > 0 else 0
            with st.expander(f"**{p['nom']}** — {fmt2(p['cap'])} restant"):
                pc1, pc2, pc3 = st.columns(3)
                pc1.metric("Capital restant", fmt2(p['cap']))
                pc2.metric("Mensualité", fmt2(p['ech']))
                pc3.metric("Mois restants", str(p['nb']))
                st.progress(pct / 100, text=f"{pct}% remboursé")
                if st.button("🗑 Supprimer", key=f"del_p_{p['id']}"):
                    D['prets'] = [x for x in D['prets'] if x['id'] != p['id']]
                    persist()
                    st.rerun()
    else:
        st.info("Aucun prêt enregistré. Restaure ton JSON de sauvegarde.")

    st.divider()
    st.markdown("**Ajouter un prêt**")
    with st.form("add_pret_form", clear_on_submit=True):
        pp1, pp2 = st.columns(2)
        with pp1:
            p_nom = st.text_input("Nom", placeholder="Regroupement crédits…")
            p_cap = st.number_input("Capital restant (€)", min_value=0.0, step=100.0)
        with pp2:
            p_ech = st.number_input("Mensualité (€)", min_value=0.0, step=10.0)
            p_nb = st.number_input("Mensualités restantes", min_value=0, step=1)
        if st.form_submit_button("✅ Enregistrer", use_container_width=True):
            D['prets'].append({'id': f"p_{int(datetime.now().timestamp()*1000)}",
                               'nom': p_nom, 'cap': float(p_cap), 'ech': float(p_ech), 'nb': int(p_nb)})
            persist()
            st.success("✓ Prêt enregistré !")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 8 — CATÉGORIES
# ══════════════════════════════════════════════════════════════════════════════
with tabs[7]:
    st.subheader("Catégories")
    st.write(f"{len(D['cats'])} catégories enregistrées.")
    for cat in D['cats']:
        cc1, cc2 = st.columns([4, 1])
        cc1.write(f"• {cat}")
        if cc2.button("🗑", key=f"del_cat_{cat}"):
            D['cats'].remove(cat)
            persist()
            st.rerun()
    with st.form("add_cat_form", clear_on_submit=True):
        new_cat = st.text_input("Nouvelle catégorie", placeholder="Ex: Animaux, Cadeaux…")
        if st.form_submit_button("Ajouter"):
            if new_cat and new_cat not in D['cats']:
                D['cats'].append(new_cat)
                persist()
                st.success(f"✓ Catégorie « {new_cat} » ajoutée.")
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ONGLET 9 — SAUVEGARDE
# ══════════════════════════════════════════════════════════════════════════════
with tabs[8]:
    st.subheader("💾 Sauvegarde & Restauration")

    bk1, bk2 = st.columns(2)

    with bk1:
        st.markdown("**📥 Exporter les données**")
        backup = {
            'version': 2, 'date': datetime.now().isoformat(),
            'tx': D['tx'], 'cats': D['cats'], 'prets': D['prets'],
            'rec': D['rec'], 'sol': D['sol'], 'overdraft': D['overdraft']
        }
        backup_json = json.dumps(backup, ensure_ascii=False, indent=2)
        st.download_button(
            "⬇️ Télécharger la sauvegarde JSON",
            data=backup_json,
            file_name=f"budget_backup_{datetime.now().strftime('%Y-%m-%d')}.json",
            mime="application/json",
            use_container_width=True
        )
        st.info(f"**{len(D['tx'])}** transactions · **{len(D['rec'])}** récurrentes · **{len(D['prets'])}** prêts")

    with bk2:
        st.markdown("**📤 Restaurer depuis un fichier JSON**")
        st.warning("⚠️ Cela remplacera toutes les données actuelles.")
        uploaded = st.file_uploader("Choisir le fichier JSON", type=['json'])
        if uploaded:
            try:
                data_in = json.load(uploaded)
                if st.button("🔄 Restaurer", type="primary", use_container_width=True):
                    if data_in.get('tx'): D['tx'] = data_in['tx']
                    if data_in.get('cats'): D['cats'] = data_in['cats']
                    if data_in.get('prets'): D['prets'] = data_in['prets']
                    if data_in.get('rec'): D['rec'] = data_in['rec']
                    if data_in.get('sol'): D['sol'] = data_in['sol']
                    if data_in.get('overdraft'): D['overdraft'] = data_in['overdraft']
                    persist()
                    st.success(f"✓ {len(D['tx'])} transactions restaurées !")
                    st.rerun()
            except Exception as e:
                st.error(f"Erreur : {e}")

    st.divider()
    st.markdown("**📊 Export CSV des transactions**")
    if D['tx']:
        df_exp = pd.DataFrame([{
            'Date': t['date'], 'Compte': t['compte'], 'Catégorie': t['categorie'],
            'Type': t['type'], 'Montant': t['montant'],
            'Note': t.get('note', ''), 'AffMois': t.get('affM', ''), 'AffAnnée': t.get('affY', '')
        } for t in D['tx']])
        st.download_button("⬇️ Télécharger CSV", data=df_exp.to_csv(index=False, encoding='utf-8-sig'),
                           file_name="budget_transactions.csv", mime="text/csv", use_container_width=True)
