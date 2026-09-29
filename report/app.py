"""Streamlit leaderboard — multi-channel Kick chat activity."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.channels import list_active_channels  # noqa: E402
from ingest.config import get_settings  # noqa: E402
from ingest.snowflake_writer import (  # noqa: E402
    query_leaderboard,
    query_user_cross_channel,
    query_user_messages,
    snowflake_connection,
)

st.set_page_config(
    page_title="Kick Chat Activity",
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
    st.title("Kick Chat Activity")
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

    st.title("Kick Chat Activity")
    st.caption("Reward active Kick chatters — multi-channel data from Snowflake CORE")

    try:
        with snowflake_connection() as conn:
            channels = list_active_channels(conn)
    except Exception as exc:
        st.error(f"Snowflake connection failed: {exc}")
        st.info("Copy `.env.example` to `.env` and set SNOWFLAKE_SCHEMA=CORE.")
        return

    if not channels:
        st.warning("No active channels in CHANNELS. Seed via sql/001_ddl.sql or subscribe script.")
        return

    slug_options = [c.channel_slug for c in channels]
    default_slug = get_settings().kick_channel_slug
    default_idx = slug_options.index(default_slug) if default_slug in slug_options else 0

    tab_lb, tab_cross = st.tabs(["Channel leaderboard", "Cross-channel user"])

    with tab_lb:
        col0, col1, col2, col3 = st.columns(4)
        with col0:
            channel_slug = st.selectbox("Channel", options=slug_options, index=default_idx)
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
                    channel_slug=channel_slug,
                    days=period,
                    limit=int(limit),
                    exclude_commands=exclude_commands,
                )
        except Exception as exc:
            st.error(f"Query failed: {exc}")
            return

        if not rows:
            st.warning("No messages yet for this channel. Start webhook ingest or run an import.")
            return

        df = pd.DataFrame(rows)
        df.columns = [c.lower() for c in df.columns]
        for col in ("first_message_at", "last_message_at"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])

        st.subheader(f"Leaderboard — {channel_slug}")
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "channel_slug": "Channel",
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
            file_name=f"{channel_slug}_leaderboard_{stamp}.csv",
            mime="text/csv",
        )

        st.divider()
        st.subheader("User timeline (this channel)")
        usernames = df["username"].astype(str).tolist() if "username" in df.columns else []
        pick = st.selectbox("Select user", options=usernames, key="lb_user")
        if pick:
            user_id = int(df.loc[df["username"] == pick, "kick_user_id"].iloc[0])
            with snowflake_connection() as conn:
                msgs = query_user_messages(
                    conn,
                    kick_user_id=user_id,
                    channel_slug=channel_slug,
                    days=period,
                    limit=200,
                )
            if msgs:
                mdf = pd.DataFrame(msgs)
                mdf.columns = [c.lower() for c in mdf.columns]
                st.dataframe(mdf, use_container_width=True, hide_index=True)
                st.download_button(
                    f"Download @{pick} messages CSV",
                    data=mdf.to_csv(index=False).encode("utf-8"),
                    file_name=f"{channel_slug}_{pick}_{stamp}.csv",
                    mime="text/csv",
                )
            else:
                st.info("No messages for this user in the selected period.")

    with tab_cross:
        st.caption("Operator view: one Kick user’s involvement across all registered channels.")
        c1, c2, c3 = st.columns(3)
        with c1:
            lookup_user = st.text_input("Username", key="cross_user")
        with c2:
            lookup_id_raw = st.text_input("Or Kick user id", key="cross_id")
        with c3:
            cross_period = st.selectbox(
                "Period",
                options=[7, 30, 90, None],
                format_func=lambda d: "All time" if d is None else f"Last {d} days",
                index=1,
                key="cross_period",
            )
        if st.button("Look up"):
            kick_id = int(lookup_id_raw) if lookup_id_raw.strip().isdigit() else None
            if not kick_id and not lookup_user.strip():
                st.error("Enter a username or Kick user id.")
            else:
                try:
                    with snowflake_connection() as conn:
                        cross = query_user_cross_channel(
                            conn,
                            kick_user_id=kick_id,
                            username=lookup_user.strip() or None,
                            days=cross_period,
                        )
                except Exception as exc:
                    st.error(f"Query failed: {exc}")
                    return
                if not cross:
                    st.warning("No matching activity.")
                else:
                    cdf = pd.DataFrame(cross)
                    cdf.columns = [c.lower() for c in cdf.columns]
                    st.dataframe(cdf, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
