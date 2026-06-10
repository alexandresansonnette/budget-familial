"""
Budget Familial AS — v2.1
Architecture modulaire, source unique de vérité.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
from datetime import datetime

from modules.data import load_from_gsheet, save_to_gsheet, migrate
from pages.aujourdhui import render as render_aujourdhui
from pages.transactions import render as render_transactions
from pages.parametres import render as render_parametres
from pages.sauvegarde import render as render_sauvegarde
from pages.previsionnel import render as render_previsionnel

st.set_page_config(
    page_title="Budget Familial",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.main > div { padding-top: 0.75rem; }
.alert-danger { background:#fdf0f0; border-left:4px solid #E24B4A; padding:10px 14px;
                border-radius:6px; margin-bottom:8px; color:#791F1F; font-size:13px; }
.alert-warn   { background:#fff8e6; border-left:4px solid #D97706; padding:10px 14px;
                border-radius:6px; margin-bottom:8px; color:#7C4A00; font-size:13px; }
.alert-ok     { background:#f0faf4; border-left:4px solid #1D9E75; padding:10px 14px;
                border-radius:6px; margin-bottom:8px; color:#085041; font-size:13px; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
if "data" not in st.session_state:
    st.session_state.data = load_from_gsheet()

# Bouton rechargement forcé depuis Sheets
with st.sidebar:
    if st.button("🔄 Recharger les données"):
        del st.session_state["data"]
        st.cache_resource.clear()
        st.rerun()

D = st.session_state.data

# Migrations au démarrage
D = migrate(D)
st.session_state.data = D

if "cur_m" not in st.session_state:
    st.session_state.cur_m = datetime.now().month - 1
if "cur_y" not in st.session_state:
    st.session_state.cur_y = datetime.now().year


def persist():
    save_to_gsheet(st.session_state.data)


# ── Navigation mois (globale) ─────────────────────────────────────────────────
MOIS = ['Janvier','Février','Mars','Avril','Mai','Juin',
        'Juillet','Août','Septembre','Octobre','Novembre','Décembre']

nc1, nc2, nc3, nc4 = st.columns([1, 3, 1, 3])
with nc1:
    if st.button("◀", use_container_width=True):
        if st.session_state.cur_m == 0:
            st.session_state.cur_m = 11; st.session_state.cur_y -= 1
        else:
            st.session_state.cur_m -= 1
        st.rerun()
with nc2:
    nm = st.selectbox("Mois", range(12), index=st.session_state.cur_m,
                      format_func=lambda x: MOIS[x], label_visibility="collapsed")
    if nm != st.session_state.cur_m:
        st.session_state.cur_m = nm; st.rerun()
with nc3:
    if st.button("▶", use_container_width=True):
        if st.session_state.cur_m == 11:
            st.session_state.cur_m = 0; st.session_state.cur_y += 1
        else:
            st.session_state.cur_m += 1
        st.rerun()
with nc4:
    ny = st.selectbox("Année", range(2023, 2032),
                      index=list(range(2023, 2032)).index(st.session_state.cur_y),
                      label_visibility="collapsed")
    if ny != st.session_state.cur_y:
        st.session_state.cur_y = ny; st.rerun()

M, Y = st.session_state.cur_m, st.session_state.cur_y

st.divider()

# ── Onglets ───────────────────────────────────────────────────────────────────
tabs = st.tabs([
    "📍 Aujourd'hui",
    "📋 Transactions",
    "📈 Prévisionnel",
    "⚙️ Paramètres",
    "💾 Sauvegarde",
])

with tabs[0]:
    render_aujourdhui(D)

with tabs[1]:
    render_transactions(D, persist, cur_m=M, cur_y=Y)

with tabs[2]:
    # FIX v2.1 : persist transmis pour la sauvegarde du budget cible
    render_previsionnel(D, persist)

with tabs[3]:
    render_parametres(D, persist, M, Y)

with tabs[4]:
    render_sauvegarde(D, persist)
