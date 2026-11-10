"""Streamlit dashboard to follow the yearly teaching load (presence hours)."""

from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from teaching_load.core.config import get_settings
from teaching_load.core.data_io import store
from teaching_load.core.data_io.sync import run_sync
from teaching_load.core.features import workload

st.set_page_config(page_title="Plan de charge", page_icon="📊", layout="wide")
SETTINGS = get_settings()


def _read(fn):
    """Run ``fn(connection)`` on a short-lived writable connection (DuckDB allows one writer at a time)."""
    con = store.connect(SETTINGS.db_path)
    try:
        return fn(con)
    finally:
        con.close()


def _year_settings() -> tuple[float, date, date]:
    def load(con):
        return (
            float(store.get_setting(con, "target_hours", str(SETTINGS.default_target_hours))),
            date.fromisoformat(store.get_setting(con, "year_start", SETTINGS.default_year_start.isoformat())),
            date.fromisoformat(store.get_setting(con, "year_end", SETTINGS.default_year_end.isoformat())),
        )

    return _read(load)


def _label(row: pd.Series) -> str:
    return f"{row['course_name']} ({row['course_code']})"


# ---------------------------------------------------------------- data
target, year_start, year_end = _year_settings()
courses = _read(store.load_courses)
sessions_all = _read(store.load_sessions)
now = datetime.now()  # noqa: DTZ005

st.title("📊 Plan de charge enseignant")

if sessions_all.empty:
    st.info("Aucune donnée. Lancez une synchronisation depuis l'onglet « Données ».")

# ---------------------------------------------------------------- sidebar filters
with st.sidebar:
    st.header("Filtres")
    if not courses.empty:
        courses = courses.assign(label=courses.apply(_label, axis=1))
        selected = st.multiselect(
            "Cours comptabilisés",
            options=courses["label"].tolist(),
            default=courses.loc[courses["included"], "label"].tolist(),
            help="Retirez les cours qui ne comptent pas dans votre service. Le choix est mémorisé.",
        )
        new_included = courses["label"].isin(selected)
        if not new_included.equals(courses["included"]):
            _read(lambda con: store.save_courses(con, courses.assign(included=new_included)))
            st.rerun()
        programmes = sorted(courses["programme"].dropna().unique())
        chosen_programmes = st.multiselect("Programmes", programmes, default=programmes)
    else:
        chosen_programmes = []
    st.caption(f"Objectif : {target:g} h · {year_start:%d/%m/%Y} → {year_end:%d/%m/%Y}")

counted = sessions_all[sessions_all["included"] & sessions_all["programme"].isin(chosen_programmes)]

tab_dash, tab_detail, tab_data, tab_settings = st.tabs(["Tableau de bord", "Détail", "Données", "Paramètres"])

# ---------------------------------------------------------------- dashboard
with tab_dash:
    if counted.empty:
        st.warning("Aucune séance comptabilisée avec les filtres actuels.")
    else:
        s = workload.summarize(counted, target, year_end, now)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Réalisé à ce jour", f"{s.realised:g} h", f"{s.realised_pct:.0f} % de l'objectif")
        c2.metric("Planifié restant", f"{s.planned_remaining:g} h")
        c3.metric("Projeté fin d'année", f"{s.projected:g} h", f"{s.projected - s.target:+g} h vs objectif")
        if s.gap > 0:
            c4.metric("Reste à trouver", f"{s.gap:g} h", f"≈ {s.missing_per_week:.1f} h/semaine", delta_color="inverse")
        else:
            c4.metric("Objectif atteint", "✅", f"{-s.gap:g} h au-dessus")

        st.progress(min(s.projected_pct / 100, 1.0), text=f"Projection : {s.projected_pct:.0f} % de {s.target:g} h")

        curve = workload.cumulative_curve(counted, year_start, year_end, target, now)
        fig = go.Figure()
        fig.add_scatter(
            x=curve["date"], y=curve["linear"], name="Trajectoire linéaire", line={"dash": "dot", "color": "gray"}
        )
        fig.add_scatter(x=curve["date"], y=curve["projected"], name="Projeté (planning)", line={"color": "#9aa5b1"})
        fig.add_scatter(x=curve["date"], y=curve["realised"], name="Réalisé", line={"color": "#1f77b4", "width": 3})
        fig.add_hline(y=target, line_dash="dash", line_color="crimson", annotation_text=f"Objectif {target:g} h")
        fig.add_vline(x=now, line_color="gray", opacity=0.5)
        fig.update_layout(height=420, yaxis_title="Heures cumulées", legend={"orientation": "h"}, margin={"t": 20})
        st.plotly_chart(fig, width="stretch")

        monthly = workload.hours_by_month(counted, now)
        fig_m = go.Figure()
        fig_m.add_bar(x=monthly["month"], y=monthly["realised"], name="Réalisé", marker_color="#1f77b4")
        fig_m.add_bar(x=monthly["month"], y=monthly["planned"], name="Planifié", marker_color="#9aa5b1")
        fig_m.update_layout(barmode="stack", height=320, yaxis_title="Heures", legend={"orientation": "h"})
        st.plotly_chart(fig_m, width="stretch")

# ---------------------------------------------------------------- detail
with tab_detail:
    if not counted.empty:
        left, right = st.columns(2)
        left.subheader("Par cours")
        left.dataframe(workload.hours_by(counted, "course_name", now), hide_index=True, width="stretch")
        right.subheader("Par programme")
        right.dataframe(workload.hours_by(counted, "programme", now), hide_index=True, width="stretch")
        st.subheader("Séances")
        st.dataframe(
            counted[
                ["start_ts", "end_ts", "duration_h", "course_code", "course_name", "programme", "location", "source"]
            ],
            hide_index=True,
            width="stretch",
        )

# ---------------------------------------------------------------- data
with tab_data:
    st.subheader("Synchronisation")
    snapshots = _read(lambda con: con.execute("SELECT * FROM snapshots ORDER BY synced_at DESC").df())
    if not snapshots.empty:
        st.caption(f"Dernière synchro : {snapshots.iloc[0]['synced_at']:%d/%m/%Y %H:%M}")
    if st.button("🔄 Synchroniser Makersboard + ADE"):
        try:
            with st.spinner("Téléchargement des calendriers…"):
                result = run_sync(SETTINGS)
            st.success(
                f"{result.n_sessions} séances ({result.n_both} rapprochées, {result.n_makersboard_only} Makersboard seul, "
                f"{result.n_ade_only} ADE seul, {result.n_marked_deleted} supprimées)"
            )
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Échec de la synchronisation, base inchangée : {exc}")
    st.dataframe(snapshots, hide_index=True, width="stretch")

    st.subheader("Contrôle des sources")
    only_one = sessions_all[sessions_all["source"] != "both"]
    if only_one.empty:
        st.success("Toutes les séances sont présentes dans les deux sources.")
    else:
        st.warning(f"{len(only_one)} séance(s) présentes dans une seule source.")
        st.dataframe(only_one[["start_ts", "course_code", "course_name", "source"]], hide_index=True)

# ---------------------------------------------------------------- settings
with tab_settings:
    st.subheader("Année académique")
    with st.form("year"):
        new_target = st.number_input("Objectif (heures de présence)", value=float(target), min_value=0.0, step=10.0)
        new_start = st.date_input("Début", value=year_start)
        new_end = st.date_input("Fin", value=year_end)
        if st.form_submit_button("Enregistrer"):

            def save(con):
                store.set_setting(con, "target_hours", str(new_target))
                store.set_setting(con, "year_start", new_start.isoformat())
                store.set_setting(con, "year_end", new_end.isoformat())

            _read(save)
            st.rerun()

    st.subheader("Cours")
    if not courses.empty:
        edited = st.data_editor(
            courses[["course_code", "course_name", "programme", "included"]],
            disabled=["course_code"],
            hide_index=True,
            width="stretch",
            key="courses_editor",
        )
        if st.button("Enregistrer les cours"):
            _read(lambda con: store.save_courses(con, edited))
            st.rerun()
