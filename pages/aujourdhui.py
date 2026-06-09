"""Onglet Aujourd'hui — cockpit trésorerie."""
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime
import calendar
from modules.data import COMPTES
from modules.calculs import (
    solde_a_date, projection_fin_mois, alertes, aff_key,
    mc_depenses_mois, solde_bancaire
)
from modules.fmt import fmt, fmt2


def render(D):
    now = datetime.now()
    m_now, y_now = now.month - 1, now.year
    last_day = calendar.monthrange(y_now, m_now + 1)[1]

    # ── Init session state pour coches et one-shots ───────────────────────
    if "evt_coches" not in st.session_state:
        st.session_state.evt_coches = {}
    if "evt_one_shot" not in st.session_state:
        st.session_state.evt_one_shot = {}

    st.markdown(f"#### Cockpit — {now.strftime('%d/%m/%Y')}")

    # ── Bandeau soldes bancaires ──────────────────────────────────────────
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
            mc_html = ""
            if cpt_id == 'ca':
                mc_enc = mc_depenses_mois(D['tx'], m_now, y_now, jusqu_au=now)
                mc_html = (
                    f"<div style='margin-top:6px;font-size:12px;color:#888'>"
                    f"Encours MC : <span style='color:{COMPTES['mc']['color']};"
                    f"font-weight:600'>−{fmt2(mc_enc)}</span></div>"
                )
            st.markdown(
                f'<div style="border:1.5px solid {border};border-radius:10px;'
                f'padding:14px 16px;">'
                f'<div style="display:flex;justify-content:space-between;">'
                f'<strong style="color:{cpt["color"]}">{cpt["label"]}</strong>'
                f'<small style="color:#888">début : {fmt2(float(deb)) if deb else "—"}</small></div>'
                f'<div style="font-size:24px;font-weight:700;color:{sol_color};margin:4px 0">'
                f'{fmt2(sol_b) if sol_b is not None else "Solde non renseigné"}</div>'
                f'<small style="color:#888">Découvert : {fmt2(-od)}</small>'
                f'{mc_html}</div>',
                unsafe_allow_html=True
            )

    st.divider()

    # ── Sélecteur compte ──────────────────────────────────────────────────
    cpt_cockpit = st.radio(
        "Compte",
        ["ca", "mb"],
        format_func=lambda x: COMPTES[x]["label"],
        horizontal=True, key="cockpit_cpt"
    )
    proj = projection_fin_mois(D, cpt_cockpit)
    cpt_info = COMPTES[cpt_cockpit]
    color = cpt_info["color"]
    r_int = int(color[1:3], 16)
    g_int = int(color[3:5], 16)
    b_int = int(color[5:7], 16)

    # ── Bandeau synthèse ─────────────────────────────────────────────────
    if proj["solde_actuel"] is None:
        st.warning(f"⚠️ Solde de début de mois non renseigné pour "
                   f"{cpt_info['label']} — allez dans Paramètres > Soldes.")
    else:
        statut = proj["statut"]
        sol_fin = proj["solde_fin"]
        pb_date, pb_sol = proj["point_bas"]
        marge = proj["marge"]
        od = proj["od"]
        limite = proj["limite"]

        if statut == "ok":
            emoji, titre, bg, border = "🟢", "Fin de mois sécurisée", "#f0faf4", "#1D9E75"
        elif statut == "warn":
            emoji, titre, bg, border = "🟠", "Vigilance", "#fff8e6", "#D97706"
        else:
            emoji, titre, bg, border = "🔴", "Risque de découvert", "#fdf0f0", "#E24B4A"

        sol_color = "#E24B4A" if (sol_fin or 0) < 0 else "#1D9E75"
        marge_bloc = ""
        if statut == "ok":
            marge_bloc = f'<div style="font-size:13px;color:#1D9E75;margin-top:4px;">Marge avant découvert : {fmt2(marge)}</div>'
        od_bloc = ""
        if od > 0:
            od_bloc = f'<div style="font-size:12px;color:#888;margin-top:4px;">Découvert autorisé : {fmt2(limite)}</div>'
        manque_bloc = ""
        if proj["manque"] > 0:
            manque_bloc = f'<div style="font-size:14px;font-weight:600;color:#E24B4A;margin-top:6px;">Manque estimé : {fmt2(proj["manque"])}</div>'

        st.markdown(
            f'<div style="background:{bg};border-left:5px solid {border};'
            f'border-radius:10px;padding:16px 20px;margin-bottom:16px;">'
            f'<div style="font-size:18px;font-weight:700;margin-bottom:8px;">{emoji} {titre}</div>'
            f'<div style="font-size:15px;">Solde estimé au {last_day:02d}/{m_now+1:02d} : '
            f'<strong style="color:{sol_color}">{fmt2(sol_fin)}</strong></div>'
            f'<div style="font-size:13px;color:#555;margin-top:4px;">'
            f'Point le plus bas : <strong>{fmt2(pb_sol)}</strong> le {pb_date}</div>'
            f'{marge_bloc}{od_bloc}{manque_bloc}'
            f'</div>',
            unsafe_allow_html=True
        )

        # ── Graphique courbe mois complet ─────────────────────────────────
        if proj["jours"]:
            x_vals = [j[0] for j in proj["jours"]]
            y_vals = [j[1] for j in proj["jours"]]
            today_str = f"{now.day:02d}/{m_now+1:02d}"

            x_past  = [j[0] for j in proj["jours"] if int(j[0][:2]) <= now.day]
            y_past  = [j[1] for j in proj["jours"] if int(j[0][:2]) <= now.day]
            x_futur = [j[0] for j in proj["jours"] if int(j[0][:2]) >= now.day]
            y_futur = [j[1] for j in proj["jours"] if int(j[0][:2]) >= now.day]

            # Événements futurs pour le graphe
            evt_x, evt_y, evt_txt = [], [], []
            for date_s, sol_j, evts in proj["jours"]:
                if evts and int(date_s[:2]) > now.day:
                    # evts = [(nom, delta, cle, is_coche), ...]
                    lignes = []
                    for n, d, cle, ic in evts:
                        if not ic:  # exclure les cochés de l'affichage graphe
                            lignes.append(
                                f"{'▲' if d>0 else '▼'} {n} : {'+' if d>0 else ''}{fmt2(d)}"
                            )
                    if lignes:
                        evt_x.append(date_s)
                        evt_y.append(sol_j)
                        evt_txt.append("<br>".join(lignes))

            all_y = [v for v in y_vals if v is not None]
            fig = go.Figure()
            fig.add_hrect(
                y0=min(min(all_y)*1.15 if all_y else -500, limite*1.3), y1=0,
                fillcolor="rgba(220,50,50,0.05)", line_width=0
            )

            if x_past:
                fig.add_trace(go.Scatter(
                    x=x_past, y=y_past, mode="lines",
                    name=f"{cpt_info['label']} (réel)",
                    line=dict(color=color, width=2.5),
                    fill="tozeroy",
                    fillcolor=f"rgba({r_int},{g_int},{b_int},0.10)",
                    hovertemplate="%{x}<br>Solde : %{y:,.2f} €<extra></extra>"
                ))
            if x_futur:
                fig.add_trace(go.Scatter(
                    x=x_futur, y=y_futur, mode="lines",
                    name=f"{cpt_info['label']} (estimé)",
                    line=dict(color=color, width=2, dash="dot"),
                    fill="tozeroy",
                    fillcolor=f"rgba({r_int},{g_int},{b_int},0.04)",
                    hovertemplate="%{x}<br>Estimé : %{y:,.2f} €<extra></extra>"
                ))
            if evt_x:
                fig.add_trace(go.Scatter(
                    x=evt_x, y=evt_y, mode="markers",
                    name="Événements",
                    marker=dict(size=10, color=color, symbol="diamond",
                                line=dict(width=1.5, color="white")),
                    text=evt_txt,
                    hovertemplate="%{x}<br>%{text}<extra></extra>"
                ))

            pb_color_fig = "#E24B4A" if statut == "danger" else "#D97706"
            if pb_date and pb_date != today_str and pb_sol < (proj["solde_actuel"] or 0):
                fig.add_trace(go.Scatter(
                    x=[pb_date], y=[pb_sol], mode="markers+text",
                    marker=dict(size=12, color=pb_color_fig, symbol="triangle-down"),
                    text=[f"Min: {fmt2(pb_sol)}"], textposition="bottom center",
                    showlegend=False,
                    hovertemplate=f"Point bas<br>{fmt2(pb_sol)}<extra></extra>"
                ))

            fig.add_hline(y=0, line_color="rgba(0,0,0,0.15)", line_width=1)
            if od > 0:
                fig.add_hline(
                    y=limite, line_dash="dash", line_color="#E24B4A",
                    line_width=1.5, opacity=0.7,
                    annotation_text=f"Limite ({fmt2(limite)})",
                    annotation_position="bottom right"
                )
            if today_str in x_vals:
                fig.add_shape(
                    type="line", x0=today_str, x1=today_str, y0=0, y1=1,
                    xref="x", yref="paper",
                    line=dict(dash="dot", color="gray", width=1.5)
                )

            fig.update_layout(
                height=300,
                margin=dict(t=20, b=40, l=50, r=20),
                showlegend=False,
                yaxis_title="Solde (€)",
                hovermode="x unified",
                plot_bgcolor="rgba(0,0,0,0)"
            )
            st.plotly_chart(fig, use_container_width=True)

        # ── Point bas + événements ─────────────────────────────────────────
        col_pb, col_evts = st.columns([1, 2])
        with col_pb:
            st.markdown("**📉 Point le plus bas**")
            pb_c = "#E24B4A" if (pb_sol or 0) < 0 else ("#D97706" if (pb_sol or 0) < 300 else "#1D9E75")
            st.markdown(
                f'<div style="border:1px solid #e0e0e0;border-radius:10px;'
                f'padding:14px;text-align:center;">'
                f'<div style="font-size:12px;color:#888">{pb_date}</div>'
                f'<div style="font-size:22px;font-weight:700;color:{pb_c}">{fmt2(pb_sol)}</div>'
                f'{"<div style=\"font-size:11px;color:#E24B4A\">⚠️ Sous la limite</div>" if (pb_sol or 0) < limite else ""}'
                f'</div>',
                unsafe_allow_html=True
            )
            if cpt_cockpit == "ca":
                mc_enc = mc_depenses_mois(D["tx"], m_now, y_now, jusqu_au=now)
                mc_tot = mc_depenses_mois(D["tx"], m_now, y_now)
                mc_rest = mc_tot - mc_enc
                from modules.calculs import mc_rec_total
                mc_rest += mc_rec_total(D["rec"])
                st.markdown(
                    f'<div style="border:1px solid #e0e0e0;border-radius:10px;'
                    f'padding:12px;text-align:center;margin-top:8px;">'
                    f'<div style="font-size:11px;color:#888">Encours MC à ce jour</div>'
                    f'<div style="font-size:18px;font-weight:600;color:{COMPTES["mc"]["color"]}">−{fmt2(mc_enc)}</div>'
                    f'<div style="font-size:11px;color:#888">Restant : −{fmt2(mc_rest)}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )

        # ── Événements à venir avec cases à cocher ────────────────────────
        with col_evts:
            st.markdown("**📅 Événements à venir**")

            # Initialiser les coches pour ce compte
            if cpt_cockpit not in st.session_state.evt_coches:
                st.session_state.evt_coches[cpt_cockpit] = set()

            # Collecter tous les événements futurs
            all_evts = []
            for date_e, sol_j, evts in proj["jours"]:
                day_int = int(date_e[:2])
                if day_int > now.day:
                    for nom_e, delta_e, cle, is_coche in evts:
                        all_evts.append((date_e, nom_e, delta_e, cle, is_coche))

            if all_evts:
                for date_e, nom_e, delta_e, cle, is_coche in all_evts:
                    sign = "+" if delta_e > 0 else ""
                    c_e = "#1D9E75" if delta_e > 0 else "#E24B4A"
                    label_evt = (
                        f"~~{date_e}  {nom_e}  {sign}{fmt2(delta_e)}~~"
                        if is_coche
                        else f"{date_e}  {nom_e}  **:{('green' if delta_e > 0 else 'red')}[{sign}{fmt2(delta_e)}]**"
                    )
                    checked = st.checkbox(
                        label=f"{date_e} — {nom_e} — {sign}{fmt2(delta_e)}",
                        value=is_coche,
                        key=f"coche_{cpt_cockpit}_{cle}"
                    )
                    if checked:
                        st.session_state.evt_coches[cpt_cockpit].add(cle)
                    else:
                        st.session_state.evt_coches[cpt_cockpit].discard(cle)
            else:
                st.info("Aucun événement planifié.")

            # ── Ajouter un événement ponctuel ──────────────────────────────
            st.markdown("---")
            with st.expander("➕ Ajouter un événement ponctuel", expanded=False):
                with st.form(key=f"form_oneshot_{cpt_cockpit}", clear_on_submit=True):
                    col_j, col_n = st.columns([1, 2])
                    with col_j:
                        jour_os = st.number_input(
                            "Jour", min_value=1, max_value=last_day,
                            value=min(now.day + 1, last_day), step=1
                        )
                    with col_n:
                        nom_os = st.text_input("Libellé")
                    col_m, col_t = st.columns([1, 1])
                    with col_m:
                        mnt_os = st.number_input(
                            "Montant (€)", min_value=0.01, value=100.0, step=10.0
                        )
                    with col_t:
                        type_os = st.selectbox(
                            "Type", ["depense", "revenu"],
                            format_func=lambda x: "Dépense 💸" if x == "depense" else "Revenu 💰"
                        )
                    submitted = st.form_submit_button("➕ Ajouter", use_container_width=True)
                    if submitted and nom_os.strip():
                        if cpt_cockpit not in st.session_state.evt_one_shot:
                            st.session_state.evt_one_shot[cpt_cockpit] = []
                        st.session_state.evt_one_shot[cpt_cockpit].append({
                            "jour": int(jour_os),
                            "nom": nom_os.strip(),
                            "montant": float(mnt_os),
                            "type": type_os,
                        })
                        st.rerun()

                # Liste des one-shots existants avec suppression
                os_list = st.session_state.get("evt_one_shot", {}).get(cpt_cockpit, [])
                if os_list:
                    st.markdown("*Événements ajoutés manuellement :*")
                    for i, evt in enumerate(os_list):
                        sign = "+" if evt["type"] == "revenu" else "−"
                        c_os = st.columns([4, 1])
                        with c_os[0]:
                            c_e = "#1D9E75" if evt["type"] == "revenu" else "#E24B4A"
                            st.markdown(
                                f'<div style="font-size:12px;padding:2px 0;">'
                                f'<span style="color:#888">{evt["jour"]:02d}/{m_now+1:02d}</span> '
                                f'{evt["nom"]} '
                                f'<strong style="color:{c_e}">{sign}{fmt2(evt["montant"])}</strong>'
                                f'</div>',
                                unsafe_allow_html=True
                            )
                        with c_os[1]:
                            if st.button("🗑", key=f"del_os_{cpt_cockpit}_{i}",
                                         use_container_width=True):
                                st.session_state.evt_one_shot[cpt_cockpit].pop(i)
                                st.rerun()

        # Recommandation
        st.markdown("---")
        if statut == "ok":
            st.success(f"✓ Trésorerie positive tout le mois. Point bas {fmt2(pb_sol)} le {pb_date}.")
        elif statut == "warn":
            st.warning(f"⚠️ Solde bas à partir du {pb_date} : {fmt2(pb_sol)}.")
        else:
            st.error(f"🔴 Découvert prévu le {pb_date} : {fmt2(pb_sol)}. Manque : {fmt2(proj['manque'])}.")

    st.markdown("---")

    # ── Soldes compacts ────────────────────────────────────────────────────
    cpts_aff = [(k, v) for k, v in COMPTES.items() if k != "mc"]
    cols = st.columns(len(cpts_aff))
    for i, (cpt_id, cpt) in enumerate(cpts_aff):
        with cols[i]:
            sol = solde_a_date(D, cpt_id)
            od2 = D["overdraft"].get(cpt_id, 0)
            deb = D["sol"].get(f"{cpt_id}_{y_now}_{m_now}")
            s = "danger" if sol is not None and sol < -od2 else ("warn" if sol is not None and sol < (-od2 + 300) else "ok")
            mc_h = ""
            if cpt_id == "ca":
                mc_e = mc_depenses_mois(D["tx"], m_now, y_now, jusqu_au=now)
                mc_h = (f"<hr style='border:none;border-top:1px solid #e0e0e0;margin:6px 0'>"
                        f"<small style='color:#888'>Encours MC</small><br>"
                        f"<span style='color:{COMPTES['mc']['color']};font-weight:600'>−{fmt2(mc_e)}</span>")
            sol_c = "#E24B4A" if (sol or 0) < 0 else "#1D9E75"
            border_c = {"ok": "#1D9E75", "warn": "#D97706", "danger": "#E24B4A"}[s]
            st.markdown(
                f'<div style="border:1px solid #e0e0e0;border-left:4px solid {border_c};'
                f'border-radius:10px;padding:14px 16px;">'
                f'<strong style="font-size:13px">{cpt["label"]}</strong>'
                f'<span style="float:right;font-size:11px;color:#888">début : {fmt2(float(deb)) if deb else "—"}</span><br>'
                f'<span style="font-size:20px;font-weight:700;color:{sol_c}">{fmt2(sol)}</span>'
                f'<small style="color:#888;display:block">Découvert : {fmt2(-od2)}</small>'
                f'{mc_h}</div>',
                unsafe_allow_html=True
            )

    # ── Dernières TX ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**Dernières transactions du mois**")
    tx_now = sorted(
        [t for t in D["tx"] if aff_key(t) == (y_now, m_now)],
        key=lambda t: t["date"], reverse=True
    )[:10]
    if tx_now:
        import pandas as pd
        st.dataframe(pd.DataFrame([{
            "Date": datetime.strptime(t["date"], "%Y-%m-%d").strftime("%d/%m/%Y"),
            "Compte": COMPTES[t["compte"]]["label"].split()[0],
            "Catégorie": t["categorie"],
            "Description": t.get("note", ""),
            "Montant": f"{'−' if t['type']=='depense' else '+'}{fmt2(t['montant'])}",
        } for t in tx_now]), hide_index=True, use_container_width=True)
    else:
        st.info("Aucune transaction ce mois.")
