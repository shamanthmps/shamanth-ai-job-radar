"""
JobRadar Dashboard — Streamlit UI for the AI Job Opportunity Intelligence System.

Free tier constraints honoured:
  - Streamlit Community Cloud (free): https://streamlit.io/cloud
  - Database: Supabase free tier (500MB, 2GB bandwidth/month) or local Postgres
  - AI calls: only triggered on demand, not on every page load
  - GitHub API: uses cache, respects 60 req/hr unauthenticated limit

Run locally:
    streamlit run dashboard/app.py

Deploy free on Streamlit Cloud:
    1. Push repo to GitHub (public or private)
    2. Go to https://share.streamlit.io → Connect repo → Set secrets in UI
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to sys.path so src/ imports work
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="JobRadar",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Synchronous DB helper (psycopg2) — avoids asyncpg/event-loop issues in Streamlit
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="Connecting to database...")
def get_conn_params() -> dict:
    """Return psycopg2 connection params from secrets/env. Cached once per session."""
    url = st.secrets.get("DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not url:
        st.error("DATABASE_URL not set. Add it to .streamlit/secrets.toml.")
        st.stop()
    for key in ("GROQ_API_KEY", "LLM_MODEL", "LLM_CALL_DELAY"):
        if key in st.secrets and key not in os.environ:
            os.environ[key] = str(st.secrets[key])
    from urllib.parse import urlparse
    p = urlparse(url.split("?")[0])
    return dict(
        host=p.hostname, port=p.port or 5432,
        user=p.username, password=p.password,
        dbname=(p.path or "/postgres").lstrip("/") or "postgres",
        sslmode="require",
    )


def db_query(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a SELECT query and return list of dicts."""
    import psycopg2
    import psycopg2.extras
    try:
        conn = psycopg2.connect(**get_conn_params())
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        st.error(f"Database error: {exc}")
        return []


def db_execute(sql: str, params: tuple = ()) -> None:
    """Execute an INSERT/UPDATE statement."""
    import psycopg2
    try:
        conn = psycopg2.connect(**get_conn_params())
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
        conn.close()
    except Exception as exc:
        st.error(f"Database error: {exc}")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> str:
    """Render sidebar and return selected tab name."""
    with st.sidebar:
        st.markdown("## 🎯 JobRadar")
        st.caption("AI Job Opportunity Intelligence")
        st.divider()

        tab = st.radio(
            "Navigate",
            options=[
                "🔥 Top Picks",
                "📋 All Jobs",
                "📬 Applications",
                "📊 Insights",
                "🔬 OSS Tracker",
            ],
            index=0,
        )

        st.divider()
        st.markdown("**Quick Actions**")
        if st.button("▶ Run Pipeline Now", use_container_width=True):
            _trigger_pipeline()

        st.divider()
        st.caption("Personal project only. Never GEHC data.")
    return tab


def _trigger_pipeline() -> None:
    """Trigger pipeline from the dashboard (runs as subprocess)."""
    import subprocess
    with st.spinner("Running pipeline..."):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_pipeline.py"), "--mode", "all"],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(ROOT),
        )
    if result.returncode == 0:
        st.success("Pipeline completed successfully!")
        st.cache_data.clear()
    else:
        st.error(f"Pipeline error:\n{result.stderr[-1000:]}")


# ---------------------------------------------------------------------------
# Tab 1: Top Picks
# ---------------------------------------------------------------------------

def render_top_picks() -> None:
    st.header("🔥 Top Picks")
    st.caption("AI-scored jobs matching your TPM profile — sorted by score.")

    min_score = st.slider("Minimum score", 60, 95, 80, 5)

    data = db_query(
        "SELECT * FROM v_top_opportunities WHERE total_score >= %s ORDER BY total_score DESC LIMIT 50",
        (min_score,),
    )

    if not data:
        st.info("No jobs found above this score. Run the pipeline to fetch new jobs.")
        return

    for row in data:
        score = row.get("total_score", 0)
        label = row.get("score_label", "")
        emoji = "🔥" if score >= 90 else "🎯" if score >= 80 else "👀"

        with st.expander(
            f"{emoji} **{row.get('title', 'Unknown')}** — {row.get('company', '')} "
            f"| {score}/100 · {label} · {row.get('location', '')}",
            expanded=score >= 85,
        ):
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Score", score)
            col2.metric("Fit", (row.get("role_fit") or "—").title())
            col3.metric("Comp Probability", (row.get("compensation_probability") or "—").title())
            col4.metric("Salary Band", _format_band(row.get("salary_band")))

            if notes := row.get("ai_notes"):
                st.markdown(f"**AI Notes:** {notes}")

            if tags := row.get("fit_tags"):
                st.markdown("**Tags:** " + " · ".join(f"`{t}`" for t in tags))

            desc = row.get("description", "")
            if desc:
                with st.container():
                    st.text_area("Description", desc[:800], height=120, key=f"desc_{row['id']}", disabled=True)

            col_a, col_b, col_c = st.columns(3)
            if job_url := row.get("url"):
                col_a.link_button("View Job", job_url)
            if col_b.button("Generate Resume", key=f"res_{row['id']}"):
                _generate_resume_for_job(row)
            if col_c.button("Mark Applied", key=f"apply_{row['id']}"):
                _mark_applied(row)


def _format_band(band: str | None) -> str:
    mapping = {
        "unknown": "—",
        "below_40l": "<40L",
        "40_60l": "40–60L",
        "60_80l": "60–80L",
        "80_100l": "80–100L",
        "100l_plus": "100L+",
    }
    return mapping.get(band or "unknown", band or "—")


def _generate_resume_for_job(row: dict) -> None:
    from src.ai.resume_customizer import generate_resume_artifacts
    with st.spinner("Generating tailored resume..."):
        artifacts = generate_resume_artifacts(
            job_id=row["id"],
            title=row.get("title", ""),
            company=row.get("company", ""),
            description=row.get("description", ""),
        )
    if artifacts.get("resume_markdown"):
        st.success("Resume generated!")
        st.markdown(artifacts["resume_markdown"])
        if artifacts.get("cover_letter"):
            with st.expander("Cover Letter"):
                st.text(artifacts["cover_letter"])
        if artifacts.get("recruiter_message"):
            with st.expander("LinkedIn Message"):
                st.code(artifacts["recruiter_message"])
    else:
        st.error("Resume generation failed. Check that base_resume.md exists and LLM is configured.")


def _mark_applied(row: dict) -> None:
    from uuid import uuid4
    db_execute(
        "INSERT INTO applications (id, job_id, status, notes) VALUES (%s, %s, %s, %s)",
        (str(uuid4()), str(row["id"]), "applied", "Applied via dashboard"),
    )
    st.success("Marked as applied!")


# ---------------------------------------------------------------------------
# Tab 2: All Jobs
# ---------------------------------------------------------------------------

def render_all_jobs() -> None:
    import pandas as pd

    st.header("📋 All Jobs")
    st.caption("Full job listing with filters.")

    col1, col2, col3 = st.columns(3)
    min_score = col1.number_input("Min Score", 0, 100, 0, 5)
    source_filter = col2.text_input("Source (e.g. linkedin, ashby)", "")
    location_filter = col3.text_input("Location keyword", "")

    where = ["1=1"]
    params: list = []
    if min_score > 0:
        where.append("s.total_score >= %s")
        params.append(int(min_score))
    if source_filter:
        where.append("j.source ILIKE %s")
        params.append(source_filter)
    if location_filter:
        where.append("j.location ILIKE %s")
        params.append(f"%{location_filter}%")

    query = f"""
        SELECT j.id, j.title, j.company, j.location, j.is_remote,
               j.source, j.posted_at, j.url AS external_url,
               s.total_score, s.role_fit, s.salary_band AS estimated_salary_band
        FROM job_postings j
        LEFT JOIN job_scores s ON s.job_id = j.id
        WHERE {' AND '.join(where)}
        ORDER BY s.total_score DESC NULLS LAST, j.scraped_at DESC
        LIMIT 500
    """
    rows = db_query(query, tuple(params))

    if not rows:
        st.info("No jobs found. Run the pipeline first.")
        return

    df = pd.DataFrame([dict(r) for r in rows])
    df["score"] = df["total_score"].fillna(0).astype(int)
    df["remote"] = df["is_remote"].apply(lambda x: "✓" if x else "")
    df["link"] = df.apply(
        lambda r: f'<a href="{r["external_url"]}" target="_blank">View</a>'
        if r.get("external_url") else "",
        axis=1,
    )

    display_cols = ["title", "company", "location", "remote", "source", "score", "role_fit", "estimated_salary_band"]
    st.dataframe(
        df[display_cols].rename(columns={
            "title": "Title", "company": "Company", "location": "Location",
            "remote": "Remote", "source": "Source", "score": "Score",
            "role_fit": "Fit", "estimated_salary_band": "Salary Band"
        }),
        use_container_width=True,
        height=500,
    )
    st.caption(f"Showing {len(df)} jobs")


# ---------------------------------------------------------------------------
# Tab 3: Applications
# ---------------------------------------------------------------------------

def render_applications() -> None:
    import pandas as pd

    st.header("📬 Applications Tracker")

    rows = db_query("""
        SELECT a.id, a.status, a.applied_at, a.notes,
               j.title, j.company AS company_name, j.url AS external_url
        FROM applications a
        JOIN job_postings j ON j.id = a.job_id
        ORDER BY a.applied_at DESC
    """)

    if not rows:
        st.info("No applications tracked yet. Mark jobs as applied from the Top Picks tab.")
        return

    df = pd.DataFrame([dict(r) for r in rows])

    # Status summary
    statuses = df["status"].value_counts()
    cols = st.columns(min(len(statuses), 5))
    STATUS_EMOJI = {
        "shortlisted": "📌", "applied": "📨", "screening": "📞",
        "interview": "🗓️", "offer": "🎉", "rejected": "❌"
    }
    for i, (status, count) in enumerate(statuses.items()):
        cols[i].metric(f"{STATUS_EMOJI.get(status, '')} {status.title()}", count)

    st.divider()

    for _, row in df.iterrows():
        with st.expander(f"{row['title']} — {row['company_name']} ({row['status'].upper()})"):
            c1, c2 = st.columns(2)
            c1.write(f"**Applied:** {row.get('applied_at', '—')}")
            c2.write(f"**Status:** {row['status']}")
            if row.get("notes"):
                st.write(f"**Notes:** {row['notes']}")
            if row.get("external_url"):
                st.link_button("View Job Posting", row["external_url"])

            new_status = st.selectbox(
                "Update status",
                ["shortlisted", "applied", "screening", "interview", "offer", "rejected"],
                index=["shortlisted", "applied", "screening", "interview", "offer", "rejected"].index(row["status"]),
                key=f"status_{row['id']}",
            )
            if st.button("Update", key=f"upd_{row['id']}"):
                db_execute(
                    "UPDATE applications SET status = %s WHERE id = %s",
                    (new_status, str(row["id"])),
                )
                st.success("Updated!")
                st.rerun()


# ---------------------------------------------------------------------------
# Tab 4: Insights
# ---------------------------------------------------------------------------

def render_insights() -> None:
    import pandas as pd

    st.header("📊 Weekly Insights")
    st.caption("Trends from the last 7 days of scraping.")

    rows = db_query("""
        SELECT j.company, j.source, j.location, j.is_remote,
               j.scraped_at, s.total_score, s.salary_band AS estimated_salary_band
        FROM job_postings j
        LEFT JOIN job_scores s ON s.job_id = j.id
        WHERE j.scraped_at >= NOW() - INTERVAL '7 days'
    """)
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No data from the last 7 days yet. Run the pipeline first.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Jobs", len(df))
    col2.metric("Avg Score", f"{df['total_score'].dropna().mean():.0f}" if "total_score" in df else "—")
    col3.metric("Remote %", f"{df['is_remote'].mean() * 100:.0f}%" if "is_remote" in df else "—")
    col4.metric("Unique Companies", df["company"].nunique())

    st.divider()

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Top Companies Hiring")
        top_co = df["company"].value_counts().head(15)
        st.bar_chart(top_co)

    with col_b:
        st.subheader("Jobs by Source")
        by_source = df["source"].value_counts()
        st.bar_chart(by_source)

    st.subheader("Score Distribution")
    score_df = df["total_score"].dropna()
    if not score_df.empty:
        import numpy as np
        hist_data = pd.cut(score_df, bins=[0, 50, 60, 70, 80, 90, 100]).value_counts().sort_index()
        st.bar_chart(hist_data)

    st.subheader("Salary Band Breakdown")
    if "estimated_salary_band" in df:
        band_counts = df["estimated_salary_band"].fillna("unknown").value_counts()
        st.bar_chart(band_counts)


# ---------------------------------------------------------------------------
# Tab 5: OSS Tracker
# ---------------------------------------------------------------------------

def render_oss_tracker() -> None:
    st.header("🔬 OSS Job-Search Repo Tracker")
    st.caption(
        "Weekly GitHub scan: Python repos related to job-search automation with 50+ stars, "
        "active in the last 90 days."
    )

    col1, col2 = st.columns([3, 1])
    force = col2.button("🔄 Force Refresh", use_container_width=True)

    with st.spinner("Scanning GitHub topics..."):
        from src.research.github_tracker import format_report, run_weekly_scan
        repos = run_weekly_scan(force=force)

    if not repos:
        st.warning("No repos found. Check your GITHUB_TOKEN and network access.")
        return

    col1.success(f"Found **{len(repos)}** qualifying repos")

    import pandas as pd
    df = pd.DataFrame([{
        "Repo": r.full_name,
        "Stars": r.stars,
        "Forks": r.forks,
        "License": r.license or "—",
        "Last Push (days ago)": _days_since_str(r.pushed_at),
        "URL": r.html_url,
        "Description": r.description[:60] if r.description else "",
    } for r in repos])

    st.dataframe(
        df[["Repo", "Stars", "Forks", "License", "Last Push (days ago)", "Description"]],
        use_container_width=True,
        height=450,
    )

    with st.expander("Full text report"):
        st.text(format_report(repos[:20]))


def _days_since_str(iso: str) -> str:
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        days = (datetime.now(tz=timezone.utc) - dt).days
        return str(days)
    except Exception:
        return "—"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    tab = render_sidebar()
    get_conn_params()  # warm up connection check once per session

    if tab == "🔥 Top Picks":
        render_top_picks()
    elif tab == "📋 All Jobs":
        render_all_jobs()
    elif tab == "📬 Applications":
        render_applications()
    elif tab == "📊 Insights":
        render_insights()
    elif tab == "🔬 OSS Tracker":
        render_oss_tracker()


if __name__ == "__main__":
    main()
