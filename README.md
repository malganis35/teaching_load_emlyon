# teaching_load

Suivi du **plan de charge** enseignant (heures de présence) à partir de deux calendriers :

| Source | Apporte |
|---|---|
| **Makersboard** (iCal) | noms de cours lisibles |
| **ADE Campus** (iCal) | codes de cours, groupes, filière/programme, responsable pédagogique |

Les deux flux sont rapprochés par créneau horaire (début + fin, Europe/Paris), stockés dans **DuckDB**, et
affichés dans une application **Streamlit** : réalisé à ce jour, planifié restant, projection de fin d'année
et écart par rapport à l'objectif (220 h par défaut).

## Démarrage

```bash
make install                 # uv sync
cp .env.example .env         # puis renseigner MAKERSBOARD_ICAL_URL et ADE_ICAL_URL
make sync                    # télécharge les flux, met à jour data/teaching.duckdb
make run                     # lance le tableau de bord
```

`ADE_ICAL_URL` se donne **sans** `firstDate`/`lastDate` : les dates viennent de l'année académique
(onglet *Paramètres*).

## Fonctionnement

- `core/data_io/` : parseurs (`makersboard.py`, `ade.py`), rapprochement (`reconcile.py`), base (`store.py`), synchro (`sync.py`).
- `core/features/workload.py` : calcul des indicateurs (réalisé, projeté, écart, courbes).
- `app/streamlit_app.py` : tableau de bord, détail, données, paramètres.
- **Filtre de cours** (barre latérale) : décochez les cours qui ne comptent pas ; le choix est mémorisé en base.
- **Sécurité des données** : une synchro qui reçoit un flux vide (le flux Makersboard en renvoie parfois un)
  est relancée puis abandonnée sans rien écrire ; les séances disparues sont marquées `is_deleted`, jamais effacées.
- Les URL contiennent un jeton privé : elles restent dans `.env`, `data/` est ignoré par git.

## Qualité

```bash
make check   # ruff + mypy + pytest (couverture >= 80 %)
```
