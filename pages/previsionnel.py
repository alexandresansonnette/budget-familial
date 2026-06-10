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


def _bar_chart(rows, color, title, od=0, use_tot=False):
    """
    Graphique barres entrées/sorties + ligne solde.
    use_tot=False : barres hors neutres (vue FOYER — virements s'annulent)
    use_tot=True  : barres tout inclus (vue DÉTAIL PAR COMPTE — les
                    virements internes et l'épargne sont de vrais flux)
    """
    now = datetime.now()
    today_lbl = mois_label(now.month - 1, now.year)

    k_e = 'entrees_tot' if use_tot else 'entrees'
    k_s = 'sorties_tot' if use_tot else 'sorties'
    labels  = [r['label'] for r in rows]
    entrees = [r.get(k_e, r['entrees']) for r in rows]
    sorties = [r.get(k_s, r['sorties']) for r in rows]
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


def _carte_synthese(rows, cpt_id, cpt_info, od=0):
    """Carte synthétique solde fin période / point bas / tendance."""
    fc_rows = [r for r in rows if r['is_fc'] and r['sol_fin'] is not None]

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
    mc_color = COMPTES['mc']['color']
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
            # NB : pas de guillemets doubles imbriqués dans la f-string
            # (SyntaxError en Python < 3.12)
            mc_html = ""
            if cpt_id == 'ca':
                mc_enc = mc_depenses_mois(D['tx'], m_now, y_now, jusqu_au=now_pv)
                mc_html = (f"<div style='margin-top:6px;font-size:12px;color:#888'>"
                           f"Encours MC à ce jour : "
                           f"<span style='color:{mc_color};font-weight:600'>"
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
            _carte_synthese(rows_ca, 'ca', COMPTES['ca'],
                            od=D['overdraft'].get('ca', 0)),
            unsafe_allow_html=True
        )
    with c2:
        st.markdown(
            _carte_synthese(rows_mb, 'mb', COMPTES['mb'],
                            od=D['overdraft'].get('mb', 0)),
            unsafe_allow_html=True
        )

    st.markdown("")

    # ══ DÉTAIL PAR COMPTE (expander) ══════════════════════════════════════
    with st.expander("📊 Voir le détail par compte", expanded=False):
        st.caption("Vue par compte : les virements internes et l'épargne sont "
                   "**inclus** ici (vrais flux du compte), contrairement à la "
                   "vue foyer où ils s'annulent.")
        for cpt_id, rows_c in [('ca', rows_ca), ('mb', rows_mb)]:
            cpt = COMPTES[cpt_id]
            od = D['overdraft'].get(cpt_id, 0)
            fig_d = _bar_chart(rows_c, cpt['color'],
                               cpt['label'], od=od, use_tot=True)
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

    # ══ DÉCOMPOSITION DU PRÉVISIONNEL (v2.3) ═══════════════════════════════
    with st.expander("🔍 Décomposition du prévisionnel — comment le futur est calculé",
                     expanded=False):
        _render_decomposition(D)

    # ══ BUDGET CIBLE ═══════════════════════════════════════════════════════
    with st.expander("🎯 Budget cible mensuel", expanded=False):
        bc_cpt = st.radio("Compte", ['ca', 'mb'],
                          format_func=lambda x: COMPTES[x]['label'],
                          horizontal=True, key="bc_cpt_prev")
        bc = D.get('budget_cible', {})
        bc_data = dict(bc.get(bc_cpt, {}))

        MOIS_NOMS = ['Janvier','Février','Mars','Avril','Mai','Juin',
                     'Juillet','Août','Septembre','Octobre','Novembre','Décembre']

        # FIX v2.3 : TOUTES les catégories (même masquées) apparaissent ici.
        # Le masquage ne concerne que la saisie de NOUVELLES transactions.
        # Sinon : une catégorie masquée avec un budget cible devient invisible
        # → risque de double saisie (ex. Frais divers masqué + Divers).
        from modules.data import all_cats, visible_cats
        vis_set = set(visible_cats(D))
        cats_bc = sorted(set(all_cats(D)) - {'Virement interne', 'Épargne',
                                              'ARE / Salaire', 'Allocations',
                                              'Revenu freelance'})
        changed = False
        cols_bc = st.columns(3)
        new_bc = dict(bc_data)
        for i, cat in enumerate(cats_bc):
            with cols_bc[i % 3]:
                cur = float(bc_data.get(cat, 0))
                label_cat = cat if cat in vis_set else f"🙈 {cat} (masquée)"
                val = st.number_input(label_cat, value=cur, min_value=0.0,
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
            st.info("✏️ Modifications en attente — cliquez pour les sauvegarder.")

        # FIX v2.1 : sauvegarde explicite du budget cible
        # (avant : les modifications n'étaient jamais persistées depuis cet onglet)
        if st.button("💾 Enregistrer le budget cible", use_container_width=True,
                     key="bc_save_btn"):
            if persist is not None:
                persist()
                st.success("✓ Budget cible sauvegardé dans Google Sheets.")
            else:
                st.warning("⚠️ Fonction de sauvegarde non disponible "
                           "(persist non transmis par budget.py).")


# ══ v2.3 : Décomposition transparente du prévisionnel ═════════════════════
def _render_decomposition(D):
    """
    Affiche, par compte, le détail exact du calcul des sorties/entrées
    prévues : récurrentes (avec neutres à part) + budget cible par
    catégorie, et détecte les DOUBLONS (catégorie présente à la fois
    en récurrente et en budget cible).
    """
    from modules.data import CATS_NEUTRES
    from modules.prevision import _rec_neutre_net, detail_estimation

    st.caption(
        "**Sorties prévues** = récurrentes dépenses (hors neutres) + budget cible  |  "
        "**Entrées prévues** = récurrentes revenus (hors neutres) + revenu cible/variable  |  "
        "Les neutres (Virement interne, Épargne) sont exclus des barres "
        "mais appliqués au solde."
    )
    st.info(
        "🧠 **Apprentissage borné (v2.4)** : la prévision part du PLAN "
        "(récurrentes + cible), puis se corrige de **50 % de l'écart** avec "
        "le réalisé moyen des derniers mois (hors ⭐, outliers exclus), "
        "**plafonné à ±15 % du plan**, et seulement à partir de 3 mois "
        "d'historique. Si une récurrente augmente sans mise à jour, la "
        "prévision converge doucement vers la réalité sans jamais s'emballer."
    )

    for cpt_id in ['ca', 'mb']:
        cpt = COMPTES[cpt_id]
        st.markdown(f"### {cpt['label']}")

        # ── v2.3b : MOIS COURANT — détail du calcul ───────────────────────
        # Le mois courant n'utilise PAS récurrentes+cible : son solde de fin
        # vient de projection_fin_mois() (même moteur que le cockpit) :
        # solde bancaire ancré aujourd'hui + événements futurs du mois.
        from modules.calculs import projection_fin_mois
        proj = projection_fin_mois(D, cpt_id)
        now_dec = datetime.now()
        mois_cur = ['Janvier','Février','Mars','Avril','Mai','Juin','Juillet',
                    'Août','Septembre','Octobre','Novembre','Décembre'][now_dec.month - 1]
        with st.container(border=True):
            st.markdown(f"**🗓️ Mois courant ({mois_cur}) — comment son solde de fin "
                        f"est calculé**")
            if proj["solde_actuel"] is None:
                st.warning("Solde de début de mois non renseigné.")
            else:
                evt_rows, tot_evt = [], 0.0
                for date_e, _sol_j, evts in proj["jours"]:
                    for nom_e, delta_e, _cle, is_coche in evts:
                        if is_coche:
                            continue  # événement coché = exclu du calcul
                        evt_rows.append({
                            "Date": date_e,
                            "Événement": nom_e,
                            "Montant": ("+" if delta_e > 0 else "−") + fmt2(abs(delta_e)),
                        })
                        tot_evt += delta_e
                sol_banc = solde_bancaire(D, cpt_id)
                st.markdown(
                    f"Solde bancaire **aujourd'hui** (ancrage) : "
                    f"**{fmt2(sol_banc)}**  →  + événements restants du mois "
                    f"({fmt2(tot_evt)})  =  solde fin {mois_cur} : "
                    f"**{fmt2(proj['solde_fin'])}**"
                )
                if evt_rows:
                    st.dataframe(pd.DataFrame(evt_rows), hide_index=True,
                                 use_container_width=True)
                    st.caption(
                        "Événements = TX futures déjà saisies + récurrentes "
                        "restantes non couvertes"
                        + (" + prélèvement MC estimé en fin de mois"
                           if cpt_id == 'ca' else "")
                        + ". Identique au cockpit Aujourd'hui ; les barres de "
                        "ce mois sur le graphe ne montrent que le réalisé à date."
                    )
                else:
                    st.caption("Aucun événement restant ce mois.")

        # ── Récurrentes du compte (+ MC pour CA) ──────────────────────────
        recs = [r for r in D['rec'] if r['compte'] == cpt_id]
        recs_mc = [r for r in D['rec'] if r['compte'] == 'mc'] if cpt_id == 'ca' else []

        rec_dep_rows, rec_rev_rows, rec_neutre_rows = [], [], []
        for r in recs + recs_mc:
            via_mc = " (via MC)" if r['compte'] == 'mc' else ""
            row = {
                "Nom": r['nom'] + via_mc,
                "Catégorie": r.get('cat', '—'),
                "Jour": r['jour'],
                "Montant": fmt2(r['mnt']),
                "_mnt": r['mnt'],
                "_cat": r.get('cat', ''),
            }
            if r.get('cat') in CATS_NEUTRES:
                row["Sens"] = "+" if r['type'] == 'revenu' else "−"
                rec_neutre_rows.append(row)
            elif r['type'] == 'depense':
                rec_dep_rows.append(row)
            else:
                rec_rev_rows.append(row)

        tot_rec_dep = sum(r["_mnt"] for r in rec_dep_rows)
        tot_rec_rev = sum(r["_mnt"] for r in rec_rev_rows)

        # ── Budget cible du compte ────────────────────────────────────────
        bc = {k: float(v) for k, v in
              D.get('budget_cible', {}).get(cpt_id, {}).items() if float(v) > 0}
        tot_cible = sum(bc.values())
        rc = float(D.get('revenu_cible', {}).get(cpt_id, 0))

        c1, c2 = st.columns(2)

        with c1:
            st.markdown(f"**💸 Sorties prévues : {fmt2(tot_rec_dep + tot_cible)}**")
            st.markdown(f"*Récurrentes dépenses — {fmt2(tot_rec_dep)}*")
            if rec_dep_rows:
                st.dataframe(
                    pd.DataFrame(rec_dep_rows)[["Nom", "Catégorie", "Jour", "Montant"]],
                    hide_index=True, use_container_width=True
                )
            else:
                st.caption("Aucune récurrente dépense.")
            st.markdown(f"*Budget cible (variable) — {fmt2(tot_cible)}*")
            if bc:
                st.dataframe(
                    pd.DataFrame([{"Catégorie": k, "Montant": fmt2(v)}
                                  for k, v in sorted(bc.items())]),
                    hide_index=True, use_container_width=True
                )
            else:
                st.caption("Budget cible vide → fallback sur l'historique.")

        with c2:
            rc_label = fmt2(rc) if rc > 0 else "historique variable"
            st.markdown(f"**💰 Entrées prévues : {fmt2(tot_rec_rev + rc)}"
                        f"{'' if rc > 0 else ' + variable'}**")
            st.markdown(f"*Récurrentes revenus — {fmt2(tot_rec_rev)}*")
            if rec_rev_rows:
                st.dataframe(
                    pd.DataFrame(rec_rev_rows)[["Nom", "Catégorie", "Jour", "Montant"]],
                    hide_index=True, use_container_width=True
                )
            else:
                st.caption("Aucune récurrente revenu.")
            st.markdown(f"*Revenu cible : {rc_label}*")

            if rec_neutre_rows:
                flux = _rec_neutre_net(D, cpt_id)
                st.markdown(f"*Neutres (hors barres, dans le solde) — "
                            f"net : {fmt2(flux)}*")
                st.dataframe(
                    pd.DataFrame(rec_neutre_rows)[["Sens", "Nom", "Catégorie", "Montant"]],
                    hide_index=True, use_container_width=True
                )

        # ── Détection des doublons récurrentes ↔ budget cible ─────────────
        cats_rec_dep = {r["_cat"] for r in rec_dep_rows if r["_cat"]}
        doublons = sorted(cats_rec_dep & set(bc.keys()))
        if doublons:
            for cat_d in doublons:
                rec_cat_tot = sum(r["_mnt"] for r in rec_dep_rows
                                  if r["_cat"] == cat_d)
                st.error(
                    f"⚠️ **Doublon probable « {cat_d} »** : "
                    f"{fmt2(rec_cat_tot)} en récurrentes **ET** "
                    f"{fmt2(bc[cat_d])} en budget cible. "
                    f"Si les récurrentes couvrent déjà cette catégorie, "
                    f"mettez le budget cible « {cat_d} » à 0 — "
                    f"sinon elle est comptée deux fois dans le prévisionnel."
                )
        else:
            st.success("✓ Aucun doublon récurrente ↔ budget cible détecté.")

        # ── v2.4 : Apprentissage — Plan vs Réalisé vs Estimation ──────────
        det = detail_estimation(D, cpt_id)
        st.markdown("**🧠 Apprentissage : du plan à l'estimation**")
        app_rows = []
        for sens, lbl in [('dep', '💸 Dépenses'), ('rev', '💰 Revenus')]:
            d_ = det[sens]
            if d_['correction'] is None:
                corr_txt = "— (pas de cible ou < 3 mois)"
            elif d_['correction'] == 0:
                corr_txt = "0 (plan = réalisé ou historique insuffisant)"
            else:
                corr_txt = f"{'+' if d_['correction'] > 0 else ''}{fmt2(d_['correction'])}"
            app_rows.append({
                "": lbl,
                "Plan (réc. + cible)": fmt2(d_['plan']),
                f"Réalisé moy. ({d_['n_hist']} mois)":
                    fmt2(d_['realise']) if d_['realise'] is not None else "—",
                "Correction appliquée": corr_txt,
                "Estimation finale": fmt2(d_['estimation']),
            })
        st.dataframe(pd.DataFrame(app_rows), hide_index=True,
                     use_container_width=True)
        d_dep = det['dep']
        if (d_dep['correction'] is not None and d_dep['plan'] > 0
                and abs(d_dep['correction']) >= 0.14 * d_dep['plan'] * 0.5):
            st.warning(
                "📌 La correction dépenses est proche de sa borne (±15 % du "
                "plan) : ton réalisé s'écarte durablement de ton plan. "
                "Le tableau ci-dessous montre **quelle catégorie** dérive."
            )

        # ── v2.4b : Réalisé vs Plan PAR CATÉGORIE ─────────────────────────
        st.markdown("**📊 Réalisé vs Plan par catégorie (dépenses, "
                    "6 derniers mois, hors ⭐)**")
        cat_rows = _realise_vs_plan_par_cat(D, cpt_id, bc, rec_dep_rows)
        if cat_rows:
            st.dataframe(pd.DataFrame(cat_rows), hide_index=True,
                         use_container_width=True)
            st.caption(
                "🔴 = dérive significative (>20 € ET >25 % du plan). "
                "**Comment corriger** : si la catégorie contient une "
                "récurrente (loyer, abonnement…), vérifie son montant dans "
                "Paramètres → Récurrentes. Sinon, ajuste le budget cible "
                "ci-dessous — ou marque ⭐ les TX exceptionnelles qui "
                "polluent le réalisé."
            )
        else:
            st.caption("Pas assez d'historique pour la comparaison.")

        st.divider()


# ══ v2.4b : Réalisé vs Plan par catégorie ═════════════════════════════════
def _realise_vs_plan_par_cat(D, cpt_id, bc, rec_dep_rows, n_past=6):
    """
    Compare, catégorie par catégorie, le plan (budget cible + récurrentes
    de la catégorie) au réalisé moyen des n_past derniers mois.
    Réalisé : TX dépenses réelles (hors ⭐, hors neutres), affectation
    aff_key, MC incluse pour CA. Moyenne sur les mois ayant des données.
    Retourne les lignes triées par |écart| décroissant.
    """
    from collections import defaultdict
    from modules.calculs import aff_key, month_add
    from modules.data import CATS_NEUTRES

    now = datetime.now()
    cm, cy = now.month - 1, now.year
    months = {month_add(cm, cy, -i) for i in range(1, n_past + 1)}
    months = {(y_, m_) for m_, y_ in months}  # aff_key retourne (y, m)

    tot_par_cat = defaultdict(float)
    mois_actifs = set()
    for t in D['tx']:
        if t['type'] != 'depense':
            continue
        if t.get('exceptionnel', False):
            continue
        if t.get('categorie') in CATS_NEUTRES:
            continue
        cpt_t = t['compte']
        if cpt_t != cpt_id and not (cpt_id == 'ca' and cpt_t == 'mc'):
            continue
        ak = aff_key(t)
        if ak not in months:
            continue
        tot_par_cat[t['categorie']] += t['montant']
        mois_actifs.add(ak)

    n_actifs = len(mois_actifs)
    if n_actifs == 0:
        return []

    # Plan par catégorie : récurrentes (cat) + budget cible (cat)
    rec_par_cat = defaultdict(float)
    for r in rec_dep_rows:  # déjà filtrées : dépenses non neutres, MC incluse
        if r["_cat"]:
            rec_par_cat[r["_cat"]] += r["_mnt"]

    toutes_cats = set(tot_par_cat) | set(rec_par_cat) | set(bc)
    rows = []
    for cat in toutes_cats:
        plan_c = rec_par_cat.get(cat, 0.0) + bc.get(cat, 0.0)
        real_c = tot_par_cat.get(cat, 0.0) / n_actifs
        ecart = real_c - plan_c
        derive = abs(ecart) > 20 and (plan_c == 0 or abs(ecart) > 0.25 * plan_c)
        rows.append({
            "Catégorie": cat,
            "Plan/mois": fmt2(plan_c),
            f"Réalisé moy. ({n_actifs} mois)": fmt2(real_c),
            "Écart": f"{'+' if ecart > 0 else ''}{fmt2(ecart)}",
            "⚠": "🔴" if derive else ("🟠" if abs(ecart) > 20 else ""),
            "_abs": abs(ecart),
        })
    rows.sort(key=lambda r: -r["_abs"])
    for r in rows:
        r.pop("_abs")
    # Ligne TOTAL
    tot_plan = sum(rec_par_cat.values()) + sum(bc.values())
    tot_real = sum(tot_par_cat.values()) / n_actifs
    rows.append({
        "Catégorie": "— TOTAL —",
        "Plan/mois": fmt2(tot_plan),
        f"Réalisé moy. ({n_actifs} mois)": fmt2(tot_real),
        "Écart": f"{'+' if tot_real - tot_plan > 0 else ''}{fmt2(tot_real - tot_plan)}",
        "⚠": "",
    })
    return rows
