"""Streamlit leaderboard for AmirPhanThom Kick chat activity."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.config import get_settings  # noqa: E402
from ingest.snowflake_writer import (  # noqa: E402
    query_leaderboard,
    query_user_messages,
    snowflake_connection,
)

st.set_page_config(
    page_title="AmirPhanThom Chat Activity",
    page_icon="🟢",
    layout="wide",
)


def require_password() -> bool:
    settings = get_settings()
    expected = settings.report_password
    if "authed" not in st.session_state:
        st.session_state.authed = False
    if st.session_state.authed:
        return True
    st.title("AmirPhanThom Chat Activity")
    pwd = st.text_input("Password", type="password")
    if st.button("Unlock"):
        if pwd == expected:
            st.session_state.authed = True
            st.rerun()
        else:
            st.error("Wrong password")
    return False


def main() -> None:
    if not require_password():
        return

    st.title("AmirPhanThom Chat Activity")
    st.caption("Reward the most active Kick chatters — data from Snowflake")

    col1, col2, col3 = st.columns(3)
    with col1:
        period = st.selectbox(
            "Period",
            options=[7, 30, 90, None],
            format_func=lambda d: "All time" if d is None else f"Last {d} days",
            index=1,
        )
    with col2:
        limit = st.number_input("Top N", min_value=10, max_value=500, value=50, step=10)
    with col3:
        exclude_commands = st.checkbox("Exclude !commands", value=True)

    try:
        with snowflake_connection() as conn:
            rows = query_leaderboard(
                conn,
                days=period,
                limit=int(limit),
                exclude_commands=exclude_commands,
            )
    except Exception as exc:
        st.error(f"Snowflake connection failed: {exc}")
        st.info("Copy `.env.example` to `.env` and fill Snowflake credentials.")
        return

    if not rows:
        st.warning("No messages yet. Start the webhook ingest or run an import.")
        return

    df = pd.DataFrame(rows)
    # Normalize column names for display
    df.columns = [c.lower() for c in df.columns]
    for col in ("first_message_at", "last_message_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])

    st.subheader("Leaderboard")
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "kick_user_id": "Kick user id",
            "username": "Username",
            "message_count": st.column_config.NumberColumn("Messages"),
            "active_days": st.column_config.NumberColumn("Active days"),
            "first_message_at": st.column_config.DatetimeColumn("First msg"),
            "last_message_at": st.column_config.DatetimeColumn("Last msg"),
        },
    )

    csv = df.to_csv(index=False).encode("utf-8")
    stamp = datetime.utcnow().strftime("%Y%m%d")
    st.download_button(
        "Download leaderboard CSV",
        data=csv,
        file_name=f"amirphanthom_leaderboard_{stamp}.csv",
        mime="text/csv",
    )

    st.divider()
    st.subheader("User timeline")
    usernames = df["username"].astype(str).tolist() if "username" in df.columns else []
    pick = st.selectbox("Select user", options=usernames)
    if pick:
        user_id = int(df.loc[df["username"] == pick, "kick_user_id"].iloc[0])
        with snowflake_connection() as conn:
            msgs = query_user_messages(conn, kick_user_id=user_id, days=period, limit=200)
        if msgs:
            mdf = pd.DataFrame(msgs)
            mdf.columns = [c.lower() for c in mdf.columns]
            st.dataframe(mdf, use_container_width=True, hide_index=True)
            st.download_button(
                f"Download @{pick} messages CSV",
                data=mdf.to_csv(index=False).encode("utf-8"),
                file_name=f"amirphanthom_{pick}_{stamp}.csv",
                mime="text/csv",
            )
        else:
            st.info("No messages for this user in the selected period.")


if __name__ == "__main__":
    main()
