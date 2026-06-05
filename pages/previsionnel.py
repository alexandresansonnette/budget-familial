"""
Onglet Prévisionnel — graphique foyer + détail par compte.
Source unique : modules/prevision.py
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from modules.data import COMPTES
from modules.prevision import build_monthly_data, agreger_foyer, mois_label
from modules.calculs import solde_bancaire, mc_depenses_mois
from modules.fmt import fmt, fmt2
from datetime import datetime

MOIS_COURT = ['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc']


def _bar_chart(rows, color, title, od=0):
    """Graphique barres entrées/sorties + ligne solde pour un compte ou le foyer."""
    now = datetime.now()
    today_lbl = mois_label(now.month - 1, now.year)

    labels  = [r['label']   for r in rows]
    entrees = [r['entrees'] for r in rows]
    sorties = [r['sorties'] for r in rows]
    sols    = [r['sol_fin'] for r in rows]
    is_fc   = [r['is_fc']   for r in rows]

    op = [0.4 if f else 1.0 for f in is_fc]
    r_c = int(color[1:3], 16)
    g_c = int(color[3:5], 16)
    b_c = int(color[5:7], 16)

    fig = go.Figure()

    # Zone rouge sous 0
    sol_vals = [s for s in sols if s is not None]
    y_min = min(sol_vals) * 1.15 if sol_vals else -500
    if y_min < 0:
        fig.add_hrect(y0=y_min, y1=0, fillcolor="rgba(220,50,50,0.04)", line_width=0)

    # Barres entrées
    fig.add_trace(go.Bar(
        x=labels, y=entrees, name="Entrées",
        marker_color=[f"rgba(29,158,117,{o})" for o in op],
        offsetgroup=0,
        hovertemplate='%{x}<br>Entrées : %{y:,.0f} €<extra></extra>'
    ))

    # Barres sorties (vers le bas)
    fig.add_trace(go.Bar(
        x=labels, y=[-s for s in sorties], name="Sorties",
        marker_color=[f"rgba(226,75,74,{o})" for o in op],
        offsetgroup=1,
        customdata=sorties,
        hovertemplate='%{x}<br>Sorties : %{customdata:,.0f} €<extra></extra>'
    ))

    # Ligne solde passé
    real_pts = [(i, v) for i, v in enumerate(sols) if v is not None and not is_fc[i]]
    fc_pts   = [(i, v) for i, v in enumerate(sols) if v is not None and is_fc[i]]

    if real_pts:
        fig.add_trace(go.Scatter(
            x=[labels[i] for i, v in real_pts],
            y=[v for i, v in real_pts],
            mode='lines+markers', name='Solde',
            line=dict(color=color, width=2.5),
            marker=dict(size=6),
            hovertemplate='%{x}<br>Solde : %{y:,.0f} €<extra></extra>'
        ))

    # Ligne solde futur + IC
    if real_pts and fc_pts:
        anchor_i, anchor_v = real_pts[-1]
        x_fc = [labels[anchor_i]] + [labels[i] for i, v in fc_pts]
        y_fc = [anchor_v] + [v for i, v in fc_pts]
        # IC simple ±15%
        y_lo = [v * 0.85 for v in y_fc]
        y_hi = [v * 1.15 for v in y_fc]

        fig.add_trace(go.Scatter(
            x=x_fc + x_fc[::-1], y=y_hi + y_lo[::-1],
            fill='toself',
            fillcolor=f"rgba({r_c},{g_c},{b_c},0.10)",
            line=dict(width=0), showlegend=False, hoverinfo='skip'
        ))
        fig.add_trace(go.Scatter(
            x=x_fc, y=y_fc, mode='lines+markers',
            name='Solde estimé', showlegend=False,
            line=dict(color=color, width=1.5, dash='dot'),
            marker=dict(size=6, symbol='circle-open'),
            hovertemplate='%{x}<br>Estimé : %{y:,.0f} €<extra></extra>'
        ))

    # Ligne 0 et découvert
    fig.add_hline(y=0, line_color="rgba(0,0,0,0.15)", line_width=1)
    if od > 0:
        fig.add_hline(y=-od, line_dash="dash", line_color="#E24B4A",
                      line_width=1.2, opacity=0.6,
                      annotation_text=f"Découvert max",
                      annotation_position="bottom right")

    # Ligne aujourd'hui
    if today_lbl in labels:
        fig.add_shape(type='line', x0=today_lbl, x1=today_lbl, y0=0, y1=1,
                      xref='x', yref='paper',
                      line=dict(dash='dot', color='gray', width=1.5))

    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        barmode='group', height=360,
        hovermode='x unified',
        margin=dict(t=40, b=60, l=50, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=-0.2,
                    xanchor="center", x=0.5),
        yaxis_title="€", bargap=0.2, bargroupgap=0.05,
        plot_bgcolor='rgba(0,0,0,0)'
    )
    return fig


def _carte_synthese(rows, cpt_id, cpt_info):
    """Carte synthétique solde fin période / point bas / tendance."""
    fc_rows = [r for r in rows if r['is_fc'] and r['sol_fin'] is not None]
    od = 0  # pas de découvert foyer

    sol_fin_c = fc_rows[-1]['sol_fin'] if fc_rows else None
    sols_fc = [r['sol_fin'] for r in fc_rows]
    point_bas = min(sols_fc) if sols_fc else sol_fin_c
    pb_label = next((r['label'] for r in fc_rows if r['sol_fin'] == point_bas), "—")

    if len(sols_fc) >= 2:
        delta = sols_fc[-1] - sols_fc[0]
        if delta > 200:
            tend_txt, tend_col = "↗ En hausse", "#1D9E75"
        elif delta < -200:
            tend_txt, tend_col = "↘ En baisse", "#E24B4A"
        else:
            tend_txt, tend_col = "→ Stable", "#888"
    else:
        tend_txt, tend_col = "— Insuffisant", "#888"

    color = cpt_info['color']
    sol_color = "#E24B4A" if (sol_fin_c or 0) < 0 else "#1D9E75"
    pb_color  = "#E24B4A" if (point_bas or 0) < 0 else "#555"

    if (point_bas or 0) < -od:
        vig_txt, vig_bg, vig_border = "🔴 Risque", "#fdf0f0", "#E24B4A"
    elif (point_bas or 0) < (-od + 300):
        vig_txt, vig_bg, vig_border = "🟠 Vigilance", "#fff8e6", "#D97706"
    else:
        vig_txt, vig_bg, vig_border = "🟢 OK", "#f0faf4", "#1D9E75"

    return f"""
    <div style="border:1.5px solid {vig_border};border-radius:12px;
                background:{vig_bg};padding:16px 18px;">
        <div style="display:flex;justify-content:space-between;
                    align-items:center;margin-bottom:10px;">
            <strong style="font-size:14px;color:{color}">{cpt_info['label']}</strong>
            <span style="font-size:12px;font-weight:600;color:{vig_border}">{vig_txt}</span>
        </div>
        <div style="display:flex;gap:12px;">
            <div style="flex:1;text-align:center;">
                <div style="font-size:11px;color:#888;margin-bottom:2px;">Solde fin période</div>
                <div style="font-size:18px;font-weight:700;color:{sol_color}">
                    {fmt2(sol_fin_c) if sol_fin_c is not None else "—"}</div>
            </div>
            <div style="flex:1;text-align:center;">
                <div style="font-size:11px;color:#888;margin-bottom:2px;">Point bas ({pb_label})</div>
                <div style="font-size:16px;font-weight:600;color:{pb_color}">
                    {fmt2(point_bas) if point_bas is not None else "—"}</div>
            </div>
            <div style="flex:1;text-align:center;">
                <div style="font-size:11px;color:#888;margin-bottom:2px;">Tendance</div>
                <div style="font-size:14px;font-weight:600;color:{tend_col}">{tend_txt}</div>
            </div>
        </div>
    </div>"""


def render(D, persist=None):
    st.subheader("📈 Prévisionnel")
    st.caption(
        "**Passé** : réel · MC intégrée dans CA · Virements internes exclus  |  "
        "**Futur** : récurrentes + budget cible · pointillé"
    )

    now = datetime.now()

    # ── Calcul des données ─────────────────────────────────────────────────
    rows_ca, sol_ca = build_monthly_data(D, 'ca')
    rows_mb, sol_mb = build_monthly_data(D, 'mb')
    rows_foyer = agreger_foyer(rows_ca, rows_mb)

    if sol_ca is None:
        st.warning("⚠️ Solde CA non renseigné — allez dans Paramètres > Soldes.")
    if sol_mb is None:
        st.warning("⚠️ Solde Monabanq non renseigné — allez dans Paramètres > Soldes.")

    # ══ BANDEAU SOLDES ACTUELS ════════════════════════════════════════════
    now_pv = datetime.now()
    m_now, y_now = now_pv.month - 1, now_pv.year
    b1, b2 = st.columns(2)
    for col, cpt_id in [(b1, 'ca'), (b2, 'mb')]:
        with col:
            cpt = COMPTES[cpt_id]
            sol_b = solde_bancaire(D, cpt_id)
            od = D['overdraft'].get(cpt_id, 0)
            s = "danger" if sol_b is not None and sol_b < -od else (
                "warn" if sol_b is not None and sol_b < (-od + 300) else "ok")
            border = {"ok": "#1D9E75", "warn": "#D97706", "danger": "#E24B4A"}[s]
            sol_color = "#E24B4A" if (sol_b or 0) < 0 else "#1D9E75"
            deb = D['sol'].get(f"{cpt_id}_{y_now}_{m_now}")

            # Encours MC pour CA
            mc_html = ""
            if cpt_id == 'ca':
                mc_enc = mc_depenses_mois(D['tx'], m_now, y_now, jusqu_au=now_pv)
                mc_html = (f"<div style='margin-top:6px;font-size:12px;color:#888'>"
                           f"Encours MC à ce jour : "
                           f"<span style='color:{COMPTES["mc"]["color"]};font-weight:600'>"
                           f"−{fmt2(mc_enc)}</span></div>")

            st.markdown(
                f'<div style="border:1.5px solid {border};border-radius:10px;'
                f'padding:14px 16px;margin-bottom:12px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<strong style="color:{cpt["color"]}">{cpt["label"]}</strong>'
                f'<small style="color:#888">début : {fmt2(float(deb)) if deb else "—"}</small></div>'
                f'<div style="font-size:22px;font-weight:700;color:{sol_color};margin:4px 0">'
                f'{fmt2(sol_b) if sol_b is not None else "Solde non renseigné"}</div>'
                f'<small style="color:#888">Découvert autorisé : {fmt2(-od)}</small>'
                f'{mc_html}</div>',
                unsafe_allow_html=True
            )

    st.divider()

    # ══ GRAPHIQUE FOYER ═══════════════════════════════════════════════════
    st.markdown("### Prévisionnel global du foyer")
    fig_foyer = _bar_chart(rows_foyer, "#5A2070", "CA + Monabanq consolidés")
    st.plotly_chart(fig_foyer, use_container_width=True)

    # ══ CARTES SYNTHÉTIQUES ════════════════════════════════════════════════
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            _carte_synthese(rows_ca, 'ca', COMPTES['ca']),
            unsafe_allow_html=True
        )
    with c2:
        st.markdown(
            _carte_synthese(rows_mb, 'mb', COMPTES['mb']),
            unsafe_allow_html=True
        )

    st.markdown("")

    # ══ DÉTAIL PAR COMPTE (expander) ══════════════════════════════════════
    with st.expander("📊 Voir le détail par compte", expanded=False):
        for cpt_id, rows_c in [('ca', rows_ca), ('mb', rows_mb)]:
            cpt = COMPTES[cpt_id]
            od = D['overdraft'].get(cpt_id, 0)
            fig_d = _bar_chart(rows_c, cpt['color'],
                               cpt['label'], od=od)
            st.plotly_chart(fig_d, use_container_width=True)

    # ══ TABLEAU MENSUEL ════════════════════════════════════════════════════
    with st.expander("📋 Tableau mensuel", expanded=False):
        for cpt_id, rows_c, label_c in [
            ('ca', rows_ca, 'Crédit Agricole'),
            ('mb', rows_mb, 'Monabanq'),
        ]:
            st.markdown(f"**{label_c}**")
            df_rows = []
            for r in rows_c:
                pref = "~" if r['is_fc'] else ""
                df_rows.append({
                    'Mois':    r['label'],
                    'Entrées': f"{pref}+{round(r['entrees']):,} €".replace(",", "\u202f"),
                    'Sorties': f"{pref}−{round(r['sorties']):,} €".replace(",", "\u202f"),
                    'Solde':   f"{pref}{round(r['sol_fin']):,} €".replace(",", "\u202f")
                              if r['sol_fin'] is not None else "—",
                })
            st.dataframe(pd.DataFrame(df_rows).set_index('Mois'),
                         use_container_width=True)

    # ══ BUDGET CIBLE ═══════════════════════════════════════════════════════
    with st.expander("🎯 Budget cible mensuel", expanded=False):
        bc_cpt = st.radio("Compte", ['ca', 'mb'],
                          format_func=lambda x: COMPTES[x]['label'],
                          horizontal=True, key="bc_cpt_prev")
        bc = D.get('budget_cible', {})
        bc_data = dict(bc.get(bc_cpt, {}))

        MOIS_NOMS = ['Janvier','Février','Mars','Avril','Mai','Juin',
                     'Juillet','Août','Septembre','Octobre','Novembre','Décembre']

        from modules.data import visible_cats
        cats_bc = sorted(set(visible_cats(D)) - {'Virement interne', 'Épargne',
                                                   'ARE / Salaire', 'Allocations',
                                                   'Revenu freelance'})
        changed = False
        cols_bc = st.columns(3)
        new_bc = dict(bc_data)
        for i, cat in enumerate(cats_bc):
            with cols_bc[i % 3]:
                cur = float(bc_data.get(cat, 0))
                val = st.number_input(cat, value=cur, min_value=0.0,
                                      step=10.0, format="%.0f",
                                      key=f"bc_{bc_cpt}_{cat}")
                if val != cur:
                    new_bc[cat] = val
                    changed = True
        if changed:
            if 'budget_cible' not in D:
                D['budget_cible'] = {}
            D['budget_cible'][bc_cpt] = new_bc

        # Revenu cible
        st.divider()
        rc = float(D.get('revenu_cible', {}).get(bc_cpt, 0))
        rc_new = st.number_input(
            "💰 Revenu variable mensuel cible (0 = utiliser l'historique)",
            value=rc, min_value=0.0, step=50.0, format="%.0f",
            key=f"rc_{bc_cpt}_prev"
        )
        if rc_new != rc:
            if 'revenu_cible' not in D:
                D['revenu_cible'] = {}
            D['revenu_cible'][bc_cpt] = rc_new
            changed = True

        if changed:
            st.success("✓ Budget cible mis à jour — sauvegarde à la prochaine action")
