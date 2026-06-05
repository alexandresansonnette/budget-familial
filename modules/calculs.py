"""
Budget Familial AS — Module calculs
Source unique de vérité pour tous les calculs financiers.

Règles fondamentales :
- Solde = solde_debut + Σ TX réelles du mois
- MC : dépenses affectées à un mois, déduites du CA en fin de mois
- Pas de TX récurrentes : les récurrentes servent uniquement au prévisionnel
- Une seule fonction pour chaque calcul MC
"""
import calendar
from datetime import datetime, date
from collections import defaultdict
from modules.data import mc_aff_from_date, CATS_NEUTRES, CATS_REVENUS


# ── Clé d'affectation d'une transaction ──────────────────────────────────────
def aff_key(t):
    """Retourne (year, month_0indexed) du mois auquel la TX est affectée."""
    if t.get("compte") == "mc":
        return (int(t["affY"]), int(t["affM"]))
    d = datetime.strptime(t["date"], "%Y-%m-%d")
    return (d.year, d.month - 1)


def month_add(m, y, n):
    """Ajoute n mois à (m, y) 0-indexed."""
    total = y * 12 + m + n
    return total % 12, total // 12


# ── MC : fonctions centralisées ───────────────────────────────────────────────
def mc_depenses_mois(tx, m, y, jusqu_au=None):
    """
    Total des dépenses MC affectées au mois (m, y).
    jusqu_au : datetime optionnel — filtre sur la date réelle de la TX.
    """
    txs = [t for t in tx
           if t["compte"] == "mc"
           and t["type"] == "depense"
           and aff_key(t) == (y, m)]
    if jusqu_au is not None:
        txs = [t for t in txs
               if datetime.strptime(t["date"], "%Y-%m-%d") <= jusqu_au]
    return sum(t["montant"] for t in txs)


def mc_rec_total(rec):
    """Total mensuel des récurrentes MC dépenses."""
    return sum(r["mnt"] for r in rec
               if r["compte"] == "mc" and r["type"] == "depense")


# ── Soldes ───────────────────────────────────────────────────────────────────
def get_sol(sol_dict, cpt, m, y):
    v = sol_dict.get(f"{cpt}_{y}_{m}")
    return float(v) if v is not None else None


def set_sol(sol_dict, cpt, m, y, v):
    k = f"{cpt}_{y}_{m}"
    if v is not None:
        sol_dict[k] = v
    else:
        sol_dict.pop(k, None)


def resolve_sol(D, cpt_id, target_m, target_y):
    """
    Retourne (solde_debut_mois, source) en cherchant le solde saisi
    le plus proche et en propageant via les TX réelles.
    """
    # Direct ?
    v = get_sol(D["sol"], cpt_id, target_m, target_y)
    if v is not None:
        return v, "saisi"

    target_abs = target_y * 12 + target_m
    candidates = []
    for key, val in D["sol"].items():
        parts = key.split("_")
        if len(parts) == 3 and parts[0] == cpt_id:
            try:
                ky, km = int(parts[1]), int(parts[2])
                candidates.append((ky * 12 + km, km, ky, float(val)))
            except ValueError:
                pass

    if not candidates:
        return None, None

    past = [(a, m, y, v) for a, m, y, v in candidates if a <= target_abs]
    future = [(a, m, y, v) for a, m, y, v in candidates if a > target_abs]

    if past:
        src_abs, src_m, src_y, src_val = max(past, key=lambda x: x[0])
    elif future:
        src_abs, src_m, src_y, src_val = min(future, key=lambda x: x[0])
    else:
        return None, None

    sol = src_val
    step = 1 if src_abs <= target_abs else -1
    cur_abs = src_abs
    while cur_abs != target_abs:
        if step == 1:
            cur_m, cur_y = cur_abs % 12, cur_abs // 12
            mvt = _mvt_net(D, cpt_id, cur_m, cur_y)
            sol += mvt
        else:
            prev_abs = cur_abs - 1
            prev_m, prev_y = prev_abs % 12, prev_abs // 12
            mvt = _mvt_net(D, cpt_id, prev_m, prev_y)
            sol -= mvt
        cur_abs += step

    return sol, "calculé"


def _mvt_net(D, cpt_id, m, y):
    """Mouvement net réel d'un compte sur un mois (revenus - dépenses - MC si CA)."""
    tx_m = [t for t in D["tx"]
            if t["compte"] == cpt_id and aff_key(t) == (y, m)]
    mvt = sum(t["montant"] if t["type"] == "revenu" else -t["montant"]
              for t in tx_m)
    if cpt_id == "ca":
        mvt -= mc_depenses_mois(D["tx"], m, y)
    return mvt


def solde_a_date(D, cpt_id):
    """Solde réel du compte à l'instant présent."""
    now = datetime.now()
    m, y = now.month - 1, now.year
    deb = get_sol(D["sol"], cpt_id, m, y)
    if deb is None:
        return None
    txs = [t for t in D["tx"]
           if t["compte"] == cpt_id
           and aff_key(t) == (y, m)
           and datetime.strptime(t["date"], "%Y-%m-%d") <= now]
    sol = deb + sum(t["montant"] if t["type"] == "revenu" else -t["montant"]
                    for t in txs)
    # MC déjà passée sur CA
    if cpt_id == "ca":
        sol -= mc_depenses_mois(D["tx"], m, y, jusqu_au=now)
    return sol


# ── Transactions filtrées ────────────────────────────────────────────────────
def tx_of_month(D, m, y, cpt_filter=None):
    """TX affectées au mois (m, y), filtrées par compte si précisé."""
    txs = [t for t in D["tx"] if aff_key(t) == (y, m)]
    if cpt_filter:
        txs = [t for t in txs if t["compte"] == cpt_filter]
    return txs


def tx_mc_period(D, m, y):
    """
    TX MC correspondant à la période de facturation du mois (m, y) 0-indexed.
    Période : du 25/(m-1) au 24/m.
    """
    cal_m = m + 1  # mois 1-indexed
    cal_y = y
    # Début période : 25 du mois précédent
    if cal_m == 1:
        start = date(cal_y - 1, 12, 25)
    else:
        start = date(cal_y, cal_m - 1, 25)
    # Fin période : 24 du mois courant
    end = date(cal_y, cal_m, 24)
    return [t for t in D["tx"]
            if t["compte"] == "mc"
            and start <= datetime.strptime(t["date"], "%Y-%m-%d").date() <= end]


# ── Alertes et récurrentes futures ───────────────────────────────────────────
def alertes(D, cpt_id):
    od = D["overdraft"].get(cpt_id, 0)
    solde = solde_a_date(D, cpt_id)
    if solde is None:
        return []
    alts = []
    if solde < -od:
        alts.append(("danger", f"Solde dans le rouge"))
    elif solde < (-od + 300):
        alts.append(("warn", f"Solde proche de la limite"))
    return alts


def rec_futures(D, cpt_id):
    """Récurrentes du compte qui n'ont pas encore de TX réelle ce mois."""
    now = datetime.now()
    m, y = now.month - 1, now.year
    # TX du mois par nom (pour détecter si déjà saisie manuellement)
    tx_noms = {t.get("note", "").strip().lower()
               for t in D["tx"] if aff_key(t) == (y, m) and t["compte"] == cpt_id}
    result = []
    for r in D["rec"]:
        if r["compte"] != cpt_id:
            continue
        if r["jour"] <= now.day:
            continue  # déjà passé
        if r["nom"].strip().lower() in tx_noms:
            continue  # déjà saisie
        result.append(r)
    return sorted(result, key=lambda r: r["jour"])


# ── Projection fin de mois ───────────────────────────────────────────────────
def projection_fin_mois(D, cpt_id):
    """
    Projette le solde jour par jour depuis le début du mois jusqu'à la fin.
    Source unique : sol_debut + TX réelles + récurrentes manquantes + MC.
    """
    now = datetime.now()
    m, y = now.month - 1, now.year
    last_day = calendar.monthrange(y, m + 1)[1]
    od = D["overdraft"].get(cpt_id, 0)
    limite = -od

    sol_debut, _ = resolve_sol(D, cpt_id, m, y)
    if sol_debut is None:
        return {"solde_actuel": None, "jours": [], "solde_fin": None,
                "point_bas": (None, None), "statut": "ok",
                "od": od, "marge": None, "limite": limite}

    solde_act = solde_a_date(D, cpt_id)

    # Construire deltas jour par jour
    daily = defaultdict(list)  # jour → [(nom, delta, is_future)]

    # 1. TX réelles du mois
    for t in D["tx"]:
        if t["compte"] != cpt_id:
            continue
        if aff_key(t) != (y, m):
            continue
        d_obj = datetime.strptime(t["date"], "%Y-%m-%d")
        delta = t["montant"] if t["type"] == "revenu" else -t["montant"]
        nom = t.get("note") or t["categorie"]
        daily[d_obj.day].append((nom, delta, d_obj.date() > now.date()))

    # 2. Récurrentes non encore saisies ce mois
    tx_noms_mois = {t.get("note", "").strip().lower()
                    for t in D["tx"] if aff_key(t) == (y, m) and t["compte"] == cpt_id}
    for r in D["rec"]:
        if r["compte"] != cpt_id:
            continue
        if r["nom"].strip().lower() in tx_noms_mois:
            continue
        delta = r["mnt"] if r["type"] == "revenu" else -r["mnt"]
        daily[r["jour"]].append((r["nom"], delta, True))

    # 3. Prélèvement MC total sur CA en fin de mois
    if cpt_id == "ca":
        mc_tot = mc_depenses_mois(D["tx"], m, y)
        mc_rec = mc_rec_total(D["rec"])
        # Récurrentes MC non encore saisies
        mc_rec_noms = {r["nom"].strip().lower() for r in D["rec"]
                       if r["compte"] == "mc" and r["type"] == "depense"}
        tx_mc_noms = {t.get("note", "").strip().lower()
                      for t in D["tx"] if t["compte"] == "mc" and aff_key(t) == (y, m)}
        mc_rec_manquant = sum(r["mnt"] for r in D["rec"]
                              if r["compte"] == "mc" and r["type"] == "depense"
                              and r["nom"].strip().lower() not in tx_mc_noms)
        mc_a_prelever = mc_tot + mc_rec_manquant
        if mc_a_prelever > 0:
            daily[last_day].append(("Prélèvement MC", -mc_a_prelever, True))

    # Rejouer depuis sol_debut
    sol = sol_debut
    jours = []
    point_bas_sol = sol_debut
    point_bas_jour = 1

    for day in range(1, last_day + 1):
        evts = daily.get(day, [])
        for _, delta, _ in evts:
            sol += delta
        date_str = f"{day:02d}/{m+1:02d}"
        evts_affich = [(n, d) for n, d, fut in evts if fut]
        jours.append((date_str, round(sol, 2), evts_affich))
        if sol < point_bas_sol:
            point_bas_sol = sol
            point_bas_jour = day

    sol_fin = jours[-1][1] if jours else sol_debut
    marge = sol_fin - limite
    manque = max(0.0, -(min(point_bas_sol, sol_fin) - limite))

    if point_bas_sol < limite:
        statut = "danger"
    elif point_bas_sol < limite + 300:
        statut = "warn"
    else:
        statut = "ok"

    return {
        "solde_actuel": solde_act,
        "sol_debut": sol_debut,
        "jours": jours,
        "solde_fin": sol_fin,
        "point_bas": (f"{point_bas_jour:02d}/{m+1:02d}", round(point_bas_sol, 2)),
        "point_bas_jour": point_bas_jour,
        "manque": round(manque, 2),
        "statut": statut,
        "od": od,
        "marge": round(marge, 2),
        "limite": limite,
    }
