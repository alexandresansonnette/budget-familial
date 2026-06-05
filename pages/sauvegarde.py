"""Onglet Sauvegarde — export/import JSON et CSV."""
import json
import streamlit as st
import pandas as pd
from datetime import datetime
from modules.calculs import aff_key


def render(D, persist):
    st.subheader("💾 Sauvegarde & Restauration")

    last_save = st.session_state.get("last_save_ok", "—")
    st.info(f"Dernière sauvegarde réussie : **{last_save}**")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**📥 Exporter**")
        backup = {
            "version": 3,
            "date": datetime.now().isoformat(),
            "tx": D["tx"], "cats": D["cats"], "prets": D["prets"],
            "rec": D["rec"], "sol": D["sol"], "overdraft": D["overdraft"],
            "budget_cible": D.get("budget_cible", {}),
            "revenu_cible": D.get("revenu_cible", {}),
        }
        st.download_button(
            "⬇️ Télécharger JSON",
            data=json.dumps(backup, ensure_ascii=False, indent=2),
            file_name=f"budget_{datetime.now().strftime('%Y-%m-%d')}.json",
            mime="application/json",
            use_container_width=True
        )
        st.info(f"**{len(D['tx'])}** transactions · "
                f"**{len(D['rec'])}** récurrentes · "
                f"**{len(D['prets'])}** prêts")

        if D["tx"]:
            df = pd.DataFrame([{
                "Date": t["date"],
                "Compte": t["compte"],
                "Catégorie": t["categorie"],
                "Type": t["type"],
                "Montant": t["montant"],
                "Note": t.get("note", ""),
                "Exceptionnel": t.get("exceptionnel", False),
                "AffMois": t.get("affM", ""),
                "AffAnnée": t.get("affY", ""),
            } for t in D["tx"]])
            st.download_button(
                "⬇️ Export CSV",
                data=df.to_csv(index=False, encoding="utf-8-sig"),
                file_name="budget_transactions.csv",
                mime="text/csv",
                use_container_width=True
            )

    with c2:
        st.markdown("**📤 Restaurer**")
        st.warning("⚠️ Remplace toutes les données existantes.")
        uploaded = st.file_uploader("Fichier JSON", type=["json"])
        if uploaded:
            try:
                data_in = json.load(uploaded)
                n_tx = len(data_in.get("tx", []))
                st.info(f"Fichier valide — {n_tx} transactions détectées.")
                if st.button("🔄 Restaurer", type="primary", use_container_width=True):
                    from modules.data import migrate
                    data_migrated = migrate(data_in)
                    for key in ["tx", "cats", "prets", "rec", "sol",
                                "overdraft", "budget_cible", "revenu_cible"]:
                        if key in data_migrated:
                            D[key] = data_migrated[key]
                    persist()
                    st.success(f"✓ {len(D['tx'])} transactions restaurées.")
                    st.rerun()
            except Exception as e:
                st.error(f"Erreur : {e}")
