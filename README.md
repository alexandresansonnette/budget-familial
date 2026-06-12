# 💰 Budget Familial AS

Application de **suivi budgétaire et de trésorerie familiale** construite avec
Python / Streamlit, pensée pour un usage réel au quotidien : multi-comptes,
carte à débit différé, prévisionnel auto-apprenant et rapprochement bancaire.

> Projet personnel développé par [AS — Analyses & Solutions](https://github.com/alexandresansonnette),
> avec pour objectif à terme une version générique multi-comptes proposable
> en suivi de trésorerie.

**🔗 Démo** : application déployée sur Streamlit Cloud (données privées —
captures d'écran ci-dessous).

---

## ✨ Fonctionnalités

| Onglet | Rôle |
|---|---|
| 📍 **Aujourd'hui** | Cockpit trésorerie : soldes bancaires, projection jour par jour jusqu'à la fin du mois, point bas, événements à venir cochables, simulation d'événements ponctuels |
| 📋 **Transactions** | Saisie rapide, édition inline, détection de doublons, **import CSV & PDF** de relevés avec catégorisation apprenante et rapprochement bancaire |
| 📈 **Prévisionnel** | Graphique foyer + détail par compte sur 12 mois, estimation par apprentissage borné, décomposition transparente du calcul, réalisé vs plan par catégorie |
| ⚙️ **Paramètres** | Soldes de début de mois, récurrentes (avec cycle de vie : fin, pause), catégories, prêts, découverts autorisés |
| 💾 **Sauvegarde** | Export/restauration JSON, export CSV |

---

## 🧠 Règles métier clés

Ces règles sont le cœur de l'application — elles sont couvertes par la
suite de tests (`tests/`).

### Carte à débit différé (Mastercard)
- Une dépense MC datée du **25 au 24** est affectée au mois suivant la
  période (date ≥ 25 → mois suivant). L'affectation est stockée sur la
  transaction (`affM`/`affY`) et modifiable manuellement.
- Le prélèvement MC est **déduit automatiquement** du compte courant en fin
  de mois — il ne doit jamais être saisi ni importé comme transaction
  (garde-fou à l'import : les lignes « prélèvement carte » des relevés sont
  détectées et écartées).
- Tout filtrage mensuel passe par la **clé d'affectation**, jamais par la
  date réelle.

### Soldes
- Les soldes sont **ancrés** sur les valeurs saisies en début de mois
  (Paramètres → Soldes), puis propagés via les transactions réelles.
- Distinction entre **solde bancaire** (tel qu'affiché sur le relevé, encours
  MC non déduit) et **solde réel** (encours MC déduit).

### Récurrentes
- Servent **uniquement au prévisionnel** — elles ne créent jamais de
  transactions réelles.
- Matching avec les transactions réelles par **type + montant (±2 %)**,
  indépendant du libellé.
- **Cycle de vie** : date de fin connue, pause temporaire (suspension
  d'échéances) ou suspension indéfinie — la récurrente disparaît du
  prévisionnel quand inactive et revit automatiquement après une pause.

### Prévisionnel à apprentissage borné
- Base : **plan = récurrentes actives + budget cible** (stable, pilotable).
- Correction automatique vers le réalisé historique (hors transactions
  exceptionnelles ⭐, outliers filtrés par IQR), avec garde-fous :
  **50 % de l'écart appliqué, plafonné à ±15 % du plan, minimum 3 mois
  d'historique**. Une dérive durable (récurrente non mise à jour) est
  absorbée en douceur, un mois atypique ne fait pas dérailler la prévision.
- Panneau « Décomposition » : chaque chiffre du prévisionnel est traçable
  (plan → réalisé → correction → estimation, et réalisé vs plan par
  catégorie avec détection des dérives).

### Import & catégorisation apprenante
- Import **CSV ou PDF** (extraction pdfplumber : détection de tableaux et
  de colonnes, fusion des libellés multi-lignes, filtrage des lignes
  parasites).
- **Registre de mots-clés appris** : chaque validation manuelle mémorise un
  mot-clé extrait du libellé (« tronc » nettoyé des tokens bancaires) — la
  catégorisation devient automatique au fil des imports.
- **Opérations opaques** (chèques, virements P2P type Wero/Paylib/Lydia) :
  mémorisées individuellement par date + libellé, jamais généralisées.
- **Rapprochement bancaire** : chaque import compare le relevé aux saisies
  existantes (montant + date exacte ou ±3 jours) — doublons exclus d'office
  ou signalés, et transactions de l'appli **absentes du relevé** remontées
  comme incohérences à corriger.

---

## 🏗️ Architecture

```
budget.py                  # Point d'entrée Streamlit, navigation, persist()
modules/
  data.py                  # Chargement/sauvegarde Google Sheets, migrations
  calculs.py               # Source unique des calculs : soldes, MC, projection
  prevision.py             # Prévisionnel mensuel, apprentissage borné
  categorisation.py        # Registre de mots-clés appris, opérations opaques
  extraction_pdf.py        # Extraction des relevés PDF (pdfplumber)
  fmt.py                   # Formatage monétaire
pages/
  aujourdhui.py            # Cockpit
  transactions.py          # Saisie, import, rapprochement
  previsionnel.py          # Graphiques, décomposition, budget cible
  parametres.py            # Soldes, récurrentes, catégories, prêts
  sauvegarde.py            # Export / restauration
tests/                     # Suite pytest (48 tests des règles métier)
```

**Stockage** : Google Sheets via compte de service (gspread), JSON chunké,
écriture sécurisée par onglet tampon avec relecture de contrôle avant
écriture définitive.

---

## 🚀 Installation

```bash
git clone https://github.com/alexandresansonnette/budget-familial.git
cd budget-familial
pip install -r requirements.txt
```

Créer `.streamlit/secrets.toml` avec un compte de service Google
(APIs Sheets + Drive activées) ayant accès à un classeur nommé
`Budget Familial AS` :

```toml
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "...@....iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

Lancer :

```bash
streamlit run budget.py
```

## 🧪 Tests

Les règles métier sont couvertes par une suite pytest autonome
(Streamlit, gspread et google-auth sont mockés — aucun secret requis) :

```bash
pip install pytest
python -m pytest tests/ -v
```

---

## 🗺️ Limites connues & feuille de route

- L'extraction PDF est calibrée sur des relevés tabulaires (Crédit
  Agricole, Monabanq) — les formats non tabulaires ne sont pas supportés.
- Configuration des comptes encore codée en dur (`COMPTES` dans
  `modules/data.py`) — la généralisation multi-comptes dynamique est
  l'évolution cible.
- Mono-utilisateur par déploiement (un classeur Google Sheets par foyer).

---

## 📄 Licence

Projet personnel — tous droits réservés.
