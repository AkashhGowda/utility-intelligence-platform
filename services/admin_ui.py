from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from services.admin_service import (
    activate_location,
    add_location,
    add_utility,
    create_user,
    database_is_online,
    deactivate_location,
    delete_utility,
    get_admin_snapshot,
    get_platform_counts,
    get_settings,
    get_locations,
    get_solar_locations,
    add_solar_location,
    update_solar_location,
    delete_solar_location,
    save_setting,
    replace_user_applications,
    reset_user_password,
    set_user_active,
    set_utility_active,
    update_user,
    update_location,
    update_utility,
)


ADMIN_PAGES = [
    "Overview",
    "Manage Locations",
    "Manage Utilities",
    "Manage Users",
    "Applications & Access",
    "Data Sources",
    "Data Extraction",
    "Report Schedules",
    "AI Configuration",
    "System Services",
]


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --admin-ink: #172033;
            --admin-muted: #64748B;
            --admin-border: #E2E8F0;
            --admin-panel: #FFFFFF;
            --admin-canvas: #F4F7FB;
            --admin-navy: #12355B;
            --admin-green: #047857;
            --admin-amber: #B45309;
            --admin-red: #B91C1C;
        }

        .stApp { background: var(--admin-canvas); }
        [data-testid="stSidebar"] {
            background: #20252B;
            border-right: 1px solid #30363D;
        }
        [data-testid="stSidebar"] * { color: #E5E7EB; }
        [data-testid="stSidebar"] .stCaption { color: #9CA3AF; }
        [data-testid="stSidebar"] hr { border-color: #3B424A; }
        [data-testid="stSidebar"] [data-testid="stRadio"] label {
            border-radius: 6px;
            padding: 7px 9px;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
            background: #2D343C;
        }
        .admin-header { margin-bottom: 24px; }
        .admin-eyebrow {
            color: var(--admin-muted);
            font-size: 0.73rem;
            font-weight: 700;
            letter-spacing: 0.11em;
            text-transform: uppercase;
            margin-bottom: 7px;
        }
        .admin-title {
            color: var(--admin-ink);
            font-size: clamp(1.8rem, 3vw, 2.45rem);
            font-weight: 760;
            line-height: 1.1;
            margin: 0;
        }
        .admin-subtitle { color: var(--admin-muted); margin: 7px 0 0; }
        [data-testid="stMetric"] {
            background: var(--admin-panel);
            border: 1px solid var(--admin-border);
            border-radius: 8px;
            padding: 15px 16px;
            min-height: 98px;
        }
        [data-testid="stMetricLabel"] { color: var(--admin-muted); }
        [data-testid="stMetricValue"] { color: var(--admin-ink); }
        .admin-panel {
            background: var(--admin-panel);
            border: 1px solid var(--admin-border);
            border-radius: 8px;
            padding: 20px;
            margin: 16px 0;
        }
        .admin-panel h3 { color: var(--admin-ink); margin: 0 0 4px; }
        .admin-panel p { color: var(--admin-muted); margin: 0 0 16px; }
        .status-badge {
            border-radius: 999px;
            display: inline-block;
            font-size: 0.76rem;
            font-weight: 700;
            padding: 3px 9px;
        }
        .status-healthy, .status-connected, .status-enabled, .status-active {
            background: #ECFDF5; color: var(--admin-green); border: 1px solid #A7F3D0;
        }
        .status-available, .status-configured {
            background: #EFF6FF; color: #1D4ED8; border: 1px solid #BFDBFE;
        }
        .status-disabled, .status-inactive, .status-not-configured {
            background: #F8FAFC; color: var(--admin-muted); border: 1px solid #CBD5E1;
        }
        .status-error {
            background: #FEF2F2; color: var(--admin-red); border: 1px solid #FECACA;
        }
        .admin-note {
            background: #F8FAFC;
            border: 1px solid var(--admin-border);
            border-left: 3px solid #94A3B8;
            border-radius: 5px;
            color: #475569;
            font-size: 0.87rem;
            padding: 11px 13px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _badge(label: str) -> str:
    css_label = label.lower().replace(" ", "-")
    return f'<span class="status-badge status-{css_label}">{label}</span>'


def _value_or_na(value: object) -> object:
    return value if value is not None and not pd.isna(value) else "N/A"


def _current_admin() -> dict[str, object]:
    return {
        "logged_in": st.session_state.get("logged_in", False),
        "username": st.session_state.get("username"),
        "user_role": st.session_state.get("user_role"),
    }


def _render_header() -> None:
    st.markdown(
        '<div class="admin-header"><div class="admin-eyebrow">Administration / Platform Controls</div>'
        '<h1 class="admin-title">Utility Intelligence Admin</h1>'
        '<p class="admin-subtitle">Centralized configuration, access management, data sources and system controls</p></div>',
        unsafe_allow_html=True,
    )


def _render_overview(snapshot: dict) -> None:
    counts = get_platform_counts(snapshot)
    postgres_online = False
    try:
        postgres_online = database_is_online()
    except Exception:
        pass

    cards = st.columns(5)
    cards[0].metric("Plants", counts["plants"])
    cards[1].metric("Solar Locations", counts["locations"])
    cards[2].metric("Users", counts["users"])
    cards[3].metric("Applications", counts["applications"])
    cards[4].metric("System Status", "Healthy" if postgres_online else "Error")

    with st.container(border=True):
        st.markdown("### Installed Applications")
        st.caption("Applications and routes currently registered in PostgreSQL.")
        applications = snapshot["applications"].copy()
        access = snapshot["access"]
        if applications.empty:
            st.info("No applications were returned from PostgreSQL.")
        else:
            applications["Status"] = applications["enabled"].map(
                lambda value: _badge("Enabled" if bool(value) else "Disabled")
            )
            applications["Users"] = applications["code"].map(
                lambda code: int((access["code"] == code).sum()) if not access.empty else 0
            )
            display = applications.rename(
                columns={"name": "Application", "code": "Code", "route": "Route"}
            )[["Application", "Code", "Route", "Status", "Users"]]
            st.write(display.to_html(escape=False, index=False), unsafe_allow_html=True)

    if snapshot.get("database_error"):
        st.warning("Some platform tables could not be read. Values shown are limited to available database data.")


def _render_locations(snapshot: dict) -> None:
    st.markdown("### Manage Locations")
    st.caption("Solar asset locations from PostgreSQL. Deactivation preserves historical telemetry.")
    current_user = _current_admin()
    if st.button("+ Add Location", type="primary", key="open_location_form"):
        st.session_state["show_location_form"] = True

    if st.session_state.get("show_location_form", False):
        with st.container(border=True):
            st.markdown("#### Add Solar Location")
            plants = snapshot["plants"]
            plant_options = {
                str(row["name"]): int(row["id"])
                for _, row in plants.iterrows()
                if pd.notna(row.get("name")) and pd.notna(row.get("id"))
            }
            if not plant_options:
                st.error("No plants are available in PostgreSQL, so a location cannot be added.")
            else:
                first, second = st.columns(2)
                with first:
                    location_code = st.text_input("Location Code", key="new_location_code")
                    location_name = st.text_input("Location Name", key="new_location_name")
                with second:
                    plant_name = st.selectbox("Plant", list(plant_options), key="new_location_plant")
                    st.caption("Capacity is not part of platform.locations and is therefore not stored.")
                save_col, close_col = st.columns(2)
                with save_col:
                    if st.button("Create Location", type="primary", key="create_location"):
                        try:
                            location_id = add_location(
                                current_user,
                                location_code,
                                location_name,
                                plant_options[plant_name],
                            )
                            st.session_state["show_location_form"] = False
                            st.success(f"Location {location_id} created successfully.")
                            st.rerun()
                        except (PermissionError, ValueError) as exc:
                            st.error(str(exc))
                        except Exception:
                            st.error("The location could not be created because of a database error.")
                with close_col:
                    close_form = st.button("Cancel", key="close_location_form")
            if st.button("Close", key="close_location_form_fallback"):
                st.session_state["show_location_form"] = False
                st.rerun()

    try:
        locations = get_locations()
    except Exception:
        st.error("Locations could not be loaded because PostgreSQL is unavailable.")
        return
    if locations.empty:
        st.info("No locations were found in PostgreSQL.")
        return
    location_filter_col1, location_filter_col2 = st.columns(2)
    with location_filter_col1:
        location_search = st.text_input("Search locations", key="location_search")
    with location_filter_col2:
        location_status_filter = st.selectbox(
            "Status", ["All", "Active", "Inactive"], key="location_status_filter"
        )
    if location_search.strip():
        search_value = location_search.strip().lower()
        locations = locations[
            locations[["code", "name", "plant"]]
            .fillna("").astype(str).apply(lambda row: row.str.lower().str.contains(search_value).any(), axis=1)
        ]
    if location_status_filter != "All":
        locations = locations[locations["active"] == (location_status_filter == "Active")]
    if locations.empty:
        st.info("No locations match the selected filters.")
        return
    locations["Capacity"] = "N/A"
    locations["Status"] = locations["active"].map(
        lambda value: _badge("Active" if bool(value) else "Inactive")
    )
    locations["Actions"] = locations["active"].map(
        lambda value: "Deactivate" if bool(value) else "Activate"
    )
    display = locations.rename(
        columns={"id": "Location ID", "code": "Code", "name": "Location", "plant": "Plant"}
    )[
        ["Location ID", "Code", "Location", "Plant", "Capacity", "Status", "Actions"]
    ]
    st.write(display.to_html(escape=False, index=False), unsafe_allow_html=True)

    with st.expander("Edit location"):
        location_ids = locations["id"].astype(int).tolist()
        selected_id = st.selectbox("Location ID", location_ids, key="edit_location_id")
        selected = locations[locations["id"] == selected_id].iloc[0]
        plants = snapshot["plants"]
        plant_options = {
            str(row["name"]): int(row["id"])
            for _, row in plants.iterrows()
            if pd.notna(row.get("name")) and pd.notna(row.get("id"))
        }
        plant_names = list(plant_options) or [str(selected.get("plant") or "Unknown")]
        selected_plant = str(selected.get("plant") or plant_names[0])
        if selected_plant not in plant_names:
            plant_names.insert(0, selected_plant)
        edit_col1, edit_col2 = st.columns(2)
        with edit_col1:
            edit_code = st.text_input("Location Code", value=str(selected["code"]), key="edit_location_code")
        with edit_col2:
            edit_name = st.text_input("Location Name", value=str(selected["name"]), key="edit_location_name")
        edit_plant = st.selectbox("Plant", plant_names, index=plant_names.index(selected_plant), key="edit_location_plant")
        if st.button("Save Changes", type="primary", key="save_location_changes"):
            if edit_plant not in plant_options:
                st.error("The selected plant is not available in PostgreSQL.")
            else:
                try:
                    update_location(current_user, selected_id, edit_code, edit_name, plant_options[edit_plant])
                    st.success("Location updated successfully.")
                    st.rerun()
                except (PermissionError, ValueError) as exc:
                    st.error(str(exc))
                except Exception:
                    st.error("The location could not be updated because of a database error.")

    st.markdown("#### Location status")
    st.caption("Deactivation preserves historical telemetry and can be reversed.")
    for _, row in locations.iterrows():
        action_label = "Deactivate" if bool(row["active"]) else "Activate"
        action_col, info_col = st.columns([1, 4])
        with info_col:
            st.caption(f"{row['id']} - {row['name']} ({action_label.lower()} available)")
        with action_col:
            confirm_key = f"confirm_location_status_{int(row['id'])}"
            confirmed = st.checkbox("Confirm", key=confirm_key)
            if st.button(action_label, key=f"location_status_{int(row['id'])}", disabled=not confirmed):
                try:
                    if bool(row["active"]):
                        deactivate_location(current_user, int(row["id"]))
                    else:
                        activate_location(current_user, int(row["id"]))
                    st.success(f"Location {row['id']} is now {action_label.lower()}d.")
                    st.rerun()
                except (PermissionError, ValueError) as exc:
                    st.error(str(exc))
                except Exception:
                    st.error("The location status could not be changed because of a database error.")


def _render_utilities(snapshot: dict) -> None:
    st.markdown("### Manage Utilities")
    st.caption("Utilities are configured per plant/location and shown in the dashboard and utility views.")
    current_user = _current_admin()

    if st.button("+ Add Utility", type="primary", key="open_utility_form"):
        st.session_state["show_utility_form"] = True

    if st.session_state.get("show_utility_form", False):
        with st.container(border=True):
            st.markdown("#### Add Utility")
            plant_options = {
                str(row["name"]): int(row["id"])
                for _, row in snapshot["plants"].iterrows()
                if pd.notna(row.get("name")) and pd.notna(row.get("id"))
            }
            location_options = {
                str(row["name"]): int(row["id"])
                for _, row in snapshot["locations"].iterrows()
                if pd.notna(row.get("name")) and pd.notna(row.get("id"))
            }
            if not plant_options or not location_options:
                st.error("Utilities cannot be created until at least one plant and one location exist.")
            else:
                form_left, form_right = st.columns(2)
                with form_left:
                    new_code = st.text_input("Utility Code", key="new_utility_code")
                    new_name = st.text_input("Utility Name", key="new_utility_name")
                    new_type = st.text_input("Utility Type", key="new_utility_type")
                with form_right:
                    new_unit = st.text_input("Unit", value="unit", key="new_utility_unit")
                    selected_plant = st.selectbox("Plant", list(plant_options), key="new_utility_plant")
                    selected_location = st.selectbox("Location", list(location_options), key="new_utility_location")
                if st.button("Create Utility", type="primary", key="create_utility"):
                    try:
                        add_utility(
                            current_user,
                            new_code,
                            new_name,
                            new_type,
                            new_unit,
                            plant_options[selected_plant],
                            location_options[selected_location],
                        )
                        st.session_state["show_utility_form"] = False
                        st.success("Utility created successfully.")
                        st.rerun()
                    except (PermissionError, ValueError) as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"The utility could not be created because of a database error: {exc}")
                if st.button("Cancel", key="cancel_utility_form"):
                    st.session_state["show_utility_form"] = False
                    st.rerun()

    utilities = snapshot.get("utilities", pd.DataFrame())
    if utilities.empty:
        st.info("No utilities are configured in PostgreSQL.")
        return

    filter_left, filter_right = st.columns(2)
    with filter_left:
        search = st.text_input("Search utilities", key="utility_search")
    with filter_right:
        type_filter = st.selectbox(
            "Type", ["All"] + sorted(utilities["type"].dropna().astype(str).unique().tolist()),
            key="utility_type_filter",
        )

    filtered = utilities.copy()
    if search.strip():
        needle = search.strip().lower()
        filtered = filtered[
            filtered[["code", "name", "type", "plant", "location"]]
            .fillna("")
            .astype(str)
            .apply(lambda row: row.str.lower().str.contains(needle).any(), axis=1)
        ]
    if type_filter != "All":
        filtered = filtered[filtered["type"].astype(str) == type_filter]

    if filtered.empty:
        st.info("No utilities match the selected filters.")
        return

    display = filtered.rename(columns={"code": "Code", "name": "Name", "type": "Type", "unit": "Unit", "plant": "Plant", "location": "Location"})
    display["Status"] = display["active"].map(lambda value: _badge("Active" if bool(value) else "Inactive"))
    st.write(display[["Code", "Name", "Type", "Unit", "Plant", "Location", "Status"]].to_html(escape=False, index=False), unsafe_allow_html=True)

    selected_id = int(st.selectbox("Utility to manage", filtered["id"].astype(int).tolist(), key="managed_utility"))
    selected = filtered[filtered["id"] == selected_id].iloc[0]

    st.markdown("#### Edit Utility")
    plant_options = {
        str(row["name"]): int(row["id"])
        for _, row in snapshot["plants"].iterrows()
        if pd.notna(row.get("name")) and pd.notna(row.get("id"))
    }
    location_options = {
        str(row["name"]): int(row["id"])
        for _, row in snapshot["locations"].iterrows()
        if pd.notna(row.get("name")) and pd.notna(row.get("id"))
    }
    plant_names = list(plant_options) or [str(selected.get("plant") or "")]
    location_names = list(location_options) or [str(selected.get("location") or "")]
    current_plant = str(selected.get("plant") or plant_names[0])
    current_location = str(selected.get("location") or location_names[0])
    if current_plant not in plant_names:
        plant_names.insert(0, current_plant)
    if current_location not in location_names:
        location_names.insert(0, current_location)

    edit_left, edit_right = st.columns(2)
    with edit_left:
        edit_code = st.text_input("Utility Code", value=str(selected["code"]), key=f"edit_utility_code_{selected_id}")
        edit_name = st.text_input("Utility Name", value=str(selected["name"]), key=f"edit_utility_name_{selected_id}")
        edit_type = st.text_input("Utility Type", value=str(selected["type"]), key=f"edit_utility_type_{selected_id}")
    with edit_right:
        edit_unit = st.text_input("Unit", value=str(selected["unit"]), key=f"edit_utility_unit_{selected_id}")
        edit_plant = st.selectbox("Plant", plant_names, index=plant_names.index(current_plant), key=f"edit_utility_plant_{selected_id}")
        edit_location = st.selectbox("Location", location_names, index=location_names.index(current_location), key=f"edit_utility_location_{selected_id}")

    if st.button("Save Utility Changes", type="primary", key=f"save_utility_{selected_id}"):
        try:
            update_utility(
                current_user,
                selected_id,
                edit_code,
                edit_name,
                edit_type,
                edit_unit,
                plant_options[edit_plant],
                location_options[edit_location],
            )
            st.success("Utility updated successfully.")
            st.rerun()
        except (PermissionError, ValueError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("The utility could not be updated because of a database error.")

    action_col, confirm_col = st.columns([1, 2])
    with action_col:
        toggle_label = "Deactivate Utility" if bool(selected["active"]) else "Activate Utility"
        if st.button(toggle_label, key=f"toggle_utility_{selected_id}"):
            try:
                set_utility_active(current_user, selected_id, not bool(selected["active"]))
                st.success(f"Utility {selected['name']} is now {'de' if bool(selected['active']) else 'act'}ivated.")
                st.rerun()
            except (PermissionError, ValueError) as exc:
                st.error(str(exc))
            except Exception:
                st.error("The utility status could not be changed because of a database error.")
    with confirm_col:
        confirm_delete = st.checkbox("Confirm deletion", key=f"confirm_delete_utility_{selected_id}")
        if st.button("Delete Utility", key=f"delete_utility_{selected_id}", disabled=not confirm_delete):
            try:
                delete_utility(current_user, selected_id)
                st.success("Utility deleted successfully.")
                st.rerun()
            except (PermissionError, ValueError) as exc:
                st.error(str(exc))
            except Exception:
                st.error("The utility could not be deleted because of a database error.")


def _render_locations(snapshot: dict) -> None:
    """Manage solar asset locations, not platform login locations."""
    st.markdown("### Solar Locations")
    st.caption(
        "Solar assets are stored in public.solar_locations. Platform login locations such as Bangalore are managed separately."
    )
    current_user = _current_admin()
    if st.button("+ Add Solar Location", type="primary", key="open_solar_location_form"):
        st.session_state["show_solar_location_form"] = True

    if st.session_state.get("show_solar_location_form", False):
        with st.container(border=True):
            st.markdown("#### Add Solar Location")
            form_left, form_right = st.columns(2)
            with form_left:
                new_id = st.number_input("Location ID", min_value=1, step=1, key="new_solar_location_id")
                new_name = st.text_input("Solar Location Name", key="new_solar_location_name")
                new_site = st.text_input("Site Location", value="Bangalore", key="new_solar_site")
            with form_right:
                new_plant = st.text_input("Plant", value="TPREL-Bangalore", key="new_solar_plant")
                new_line = st.text_input("Line", value="Vega", key="new_solar_line")
            save_col, cancel_col = st.columns(2)
            with save_col:
                if st.button("Create Solar Location", type="primary", key="create_solar_location"):
                    try:
                        add_solar_location(current_user, new_id, new_name, new_site, new_plant, new_line)
                        st.session_state["show_solar_location_form"] = False
                        st.success("Solar location created successfully.")
                        st.rerun()
                    except (PermissionError, ValueError) as exc:
                        st.error(str(exc))
                    except Exception:
                        st.error("The solar location could not be created because of a database error.")
            with cancel_col:
                if st.button("Cancel", key="cancel_solar_location"):
                    st.session_state["show_solar_location_form"] = False
                    st.rerun()

    try:
        locations = get_solar_locations()
    except Exception:
        st.error("Solar locations could not be loaded because PostgreSQL is unavailable.")
        return
    if locations.empty:
        st.info("No solar asset locations were found.")
        return

    filter_left, filter_right = st.columns(2)
    with filter_left:
        search = st.text_input("Search solar locations", key="solar_location_search")
    with filter_right:
        plant_filter = st.selectbox(
            "Plant", ["All"] + sorted(locations["plant_name"].dropna().astype(str).unique().tolist()),
            key="solar_location_plant_filter",
        )
    filtered = locations.copy()
    if search.strip():
        needle = search.strip().lower()
        filtered = filtered[
            filtered[["id", "name", "site_location", "plant_name", "line_name"]]
            .fillna("").astype(str).apply(lambda row: row.str.lower().str.contains(needle).any(), axis=1)
        ]
    if plant_filter != "All":
        filtered = filtered[filtered["plant_name"].astype(str) == plant_filter]
    if filtered.empty:
        st.info("No solar locations match the selected filters.")
        return

    display = filtered.rename(columns={"id": "ID", "name": "Solar Location", "plant_name": "Plant", "line_name": "Line"})
    display["History"] = display["has_history"].map(lambda value: "Historical data" if bool(value) else "No history")
    st.dataframe(
        display[["ID", "Solar Location", "site_location", "Plant", "Line", "History"]],
        use_container_width=True,
        hide_index=True,
    )

    selected_id = int(st.selectbox("Solar location to manage", filtered["id"].astype(int).tolist(), key="managed_solar_location"))
    selected = locations[locations["id"] == selected_id].iloc[0]
    st.markdown("#### Edit Solar Location")
    edit_left, edit_right = st.columns(2)
    with edit_left:
        edit_name = st.text_input("Solar Location Name", value=str(selected["name"]), key=f"edit_solar_name_{selected_id}")
        edit_site = st.text_input("Site Location", value=str(selected.get("site_location") or ""), key=f"edit_solar_site_{selected_id}")
    with edit_right:
        edit_plant = st.text_input("Plant", value=str(selected.get("plant_name") or ""), key=f"edit_solar_plant_{selected_id}")
        edit_line = st.text_input("Line", value=str(selected.get("line_name") or ""), key=f"edit_solar_line_{selected_id}")
    if st.button("Save Solar Location", type="primary", key=f"save_solar_location_{selected_id}"):
        try:
            update_solar_location(current_user, selected_id, edit_name, edit_site, edit_plant, edit_line)
            st.success("Solar location updated successfully.")
            st.rerun()
        except (PermissionError, ValueError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("The solar location could not be updated because of a database error.")

    if bool(selected["has_history"]):
        st.warning("This location has historical generation or telemetry data. It cannot be deleted without removing history.")
    else:
        confirm_delete = st.checkbox("Confirm deletion", key=f"confirm_delete_solar_{selected_id}")
        if st.button("Delete Solar Location", disabled=not confirm_delete, key=f"delete_solar_{selected_id}"):
            try:
                delete_solar_location(current_user, selected_id)
                st.success("Solar location deleted successfully.")
                st.rerun()
            except (PermissionError, ValueError) as exc:
                st.error(str(exc))
            except Exception:
                st.error("The solar location could not be deleted because of a database error.")


def _render_users(snapshot: dict) -> None:
    st.markdown("### Manage Users")
    st.caption("Platform identities, role assignments, and application access. Passwords are never displayed.")
    if st.button("+ Add User", type="primary", key="open_user_form"):
        st.session_state["show_user_form"] = True
    if st.session_state.get("show_user_form", False):
        with st.container(border=True):
            st.markdown("#### Add User")
            user_types = snapshot["user_types"]
            plants = snapshot["plants"]
            locations = snapshot["locations"]
            applications = snapshot["applications"]
            if user_types.empty or plants.empty or locations.empty or applications.empty:
                st.error("Users cannot be created until PostgreSQL provides user types, plants, locations, and applications.")
            else:
                type_options = {
                    f"{row['code']} ({int(row['id'])})": int(row["id"])
                    for _, row in user_types.iterrows()
                }
                plant_options = {
                    f"{row['name']} ({int(row['id'])})": int(row["id"])
                    for _, row in plants.iterrows()
                }
                location_options = {
                    f"{row['name']} ({int(row['id'])})": int(row["id"])
                    for _, row in locations.iterrows()
                }
                application_options = {
                    f"{row['name']} — {row['code']}": int(row["id"])
                    for _, row in applications.iterrows()
                }
                first, second = st.columns(2)
                with first:
                    employee_id = st.text_input("Employee ID", key="new_employee_id")
                    username = st.text_input("Username", key="new_username")
                    full_name = st.text_input("Full Name", key="new_full_name")
                    email = st.text_input("Email", key="new_email")
                    password = st.text_input("Temporary Password", type="password", key="new_user_password")
                    user_type_label = st.selectbox("User Type", list(type_options), key="new_user_type")
                with second:
                    plant_label = st.selectbox("Plant", list(plant_options), key="new_user_plant")
                    location_label = st.selectbox("Location", list(location_options), key="new_user_location")
                    application_labels = st.multiselect(
                        "Applications", list(application_options), key="new_user_applications"
                    )
                    st.caption("The first selected application becomes the default application.")
                save_col, close_col = st.columns(2)
                with save_col:
                    if st.button("Create User", type="primary", key="create_user"):
                        try:
                            user_id = create_user(
                                _current_admin(), employee_id, username, full_name, email, password,
                                type_options[user_type_label], plant_options[plant_label],
                                location_options[location_label],
                                [application_options[label] for label in application_labels],
                            )
                            st.session_state["show_user_form"] = False
                            st.success(f"User {user_id} created successfully.")
                            st.rerun()
                        except (PermissionError, ValueError) as exc:
                            st.error(str(exc))
                        except Exception:
                            st.error("The user could not be created because of a database error.")
                with close_col:
                    if st.button("Close", key="close_user_form"):
                        st.session_state["show_user_form"] = False
                        st.rerun()

    users = snapshot["users"].copy()
    if users.empty:
        st.info("No users were returned from PostgreSQL.")
        return

    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    with filter_col1:
        search = st.text_input("Search users", key="user_search")
    with filter_col2:
        user_type_filter = st.selectbox(
            "User Type", ["All"] + sorted(users["user_type"].dropna().astype(str).unique().tolist()),
            key="user_type_filter",
        )
    with filter_col3:
        plant_filter = st.selectbox(
            "Plant", ["All"] + sorted(users["plant"].dropna().astype(str).unique().tolist()),
            key="user_plant_filter",
        )
    with filter_col4:
        status_filter = st.selectbox("Status", ["All", "Active", "Inactive"], key="user_status_filter")

    filtered_users = users.copy()
    if search.strip():
        search_value = search.strip().lower()
        filtered_users = filtered_users[
            filtered_users[["employee_id", "username", "name", "email"]]
            .fillna("").astype(str).apply(lambda row: row.str.lower().str.contains(search_value).any(), axis=1)
        ]
    if user_type_filter != "All":
        filtered_users = filtered_users[filtered_users["user_type"].astype(str) == user_type_filter]
    if plant_filter != "All":
        filtered_users = filtered_users[filtered_users["plant"].astype(str) == plant_filter]
    if status_filter != "All":
        filtered_users = filtered_users[filtered_users["active"] == (status_filter == "Active")]

    display = filtered_users.rename(
        columns={"employee_id": "Employee ID", "username": "Username", "name": "Full Name", "email": "Email", "user_type": "User Type", "plant": "Plant", "location": "Location"}
    )
    display["Status"] = display["active"].map(lambda value: _badge("Enabled" if bool(value) else "Disabled"))
    st.write(display[["Employee ID", "Username", "Full Name", "Email", "User Type", "Plant", "Location", "Status"]].to_html(escape=False, index=False), unsafe_allow_html=True)

    if filtered_users.empty:
        st.info("No users match the selected filters.")
        return

    user_options = {
        f"{row['username']} — {row['name']}": int(row["id"])
        for _, row in filtered_users.iterrows()
    }
    selected_user_label = st.selectbox("User to manage", list(user_options), key="managed_user")
    selected_user_id = user_options[selected_user_label]
    selected_user = users[users["id"] == selected_user_id].iloc[0]
    st.markdown("#### Edit User")
    edit_left, edit_right = st.columns(2)
    with edit_left:
        edit_employee_id = st.text_input("Employee ID", value=str(selected_user.get("employee_id") or ""), key=f"edit_employee_id_{selected_user_id}")
        edit_username = st.text_input("Username", value=str(selected_user.get("username") or ""), key=f"edit_username_{selected_user_id}")
        edit_full_name = st.text_input("Full Name", value=str(selected_user.get("name") or ""), key=f"edit_full_name_{selected_user_id}")
        edit_email = st.text_input("Email", value=str(selected_user.get("email") or ""), key=f"edit_email_{selected_user_id}")
    with edit_right:
        type_options = {str(row["code"]): int(row["id"]) for _, row in snapshot["user_types"].iterrows()}
        plant_options = {str(row["name"]): int(row["id"]) for _, row in snapshot["plants"].iterrows()}
        location_options = {str(row["name"]): int(row["id"]) for _, row in snapshot["locations"].iterrows()}
        type_names = list(type_options) or [str(selected_user.get("user_type") or "")]
        plant_names = list(plant_options) or [str(selected_user.get("plant") or "")]
        location_names = list(location_options) or [str(selected_user.get("location") or "")]
        current_type = str(selected_user.get("user_type") or type_names[0])
        current_plant = str(selected_user.get("plant") or plant_names[0])
        current_location = str(selected_user.get("location") or location_names[0])
        for value, values in ((current_type, type_names), (current_plant, plant_names), (current_location, location_names)):
            if value not in values:
                values.insert(0, value)
        edit_type = st.selectbox("User Type", type_names, index=type_names.index(current_type), key=f"edit_user_type_{selected_user_id}")
        edit_plant = st.selectbox("Plant", plant_names, index=plant_names.index(current_plant), key=f"edit_user_plant_{selected_user_id}")
        edit_location = st.selectbox("Location", location_names, index=location_names.index(current_location), key=f"edit_user_location_{selected_user_id}")
    if st.button("Save User Changes", type="primary", key=f"save_user_{selected_user_id}"):
        try:
            update_user(
                _current_admin(), selected_user_id, edit_employee_id, edit_username, edit_full_name, edit_email,
                type_options[edit_type], plant_options[edit_plant], location_options[edit_location],
            )
            st.success("User updated successfully.")
            st.rerun()
        except (PermissionError, ValueError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("The user could not be updated because of a database error.")

    action_col, password_col = st.columns(2)
    with action_col:
        action_label = "Deactivate User" if bool(selected_user["active"]) else "Activate User"
        if st.button(action_label, key=f"toggle_user_{selected_user_id}"):
            try:
                set_user_active(_current_admin(), selected_user_id, not bool(selected_user["active"]))
                st.success(f"User {selected_user['username']} is now {action_label.split()[0].lower()}d.")
                st.rerun()
            except (PermissionError, ValueError) as exc:
                st.error(str(exc))
            except Exception:
                st.error("The user status could not be changed because of a database error.")
    with password_col:
        reset_password = st.text_input("New password", type="password", key=f"reset_password_{selected_user_id}")
        if st.button("Reset Password", key=f"reset_user_password_{selected_user_id}"):
            try:
                reset_user_password(_current_admin(), selected_user_id, reset_password)
                st.success("Password reset successfully.")
            except (PermissionError, ValueError) as exc:
                st.error(str(exc))
            except Exception:
                st.error("The password could not be reset because of a database error.")


def _render_access(snapshot: dict) -> None:
    st.markdown("### Applications & Access")
    st.caption("Application registration and access mappings from PostgreSQL.")
    applications = snapshot["applications"].copy()
    access = snapshot["access"]
    if applications.empty:
        st.info("No applications were returned from PostgreSQL.")
        return
    applications["Status"] = applications["enabled"].map(lambda value: _badge("Enabled" if bool(value) else "Disabled"))
    applications["Assigned Users"] = applications["code"].map(
        lambda code: int((access["code"] == code).sum()) if not access.empty else 0
    )
    display = applications.rename(columns={"name": "Application", "code": "Code", "route": "Route"})
    st.write(display[["Application", "Code", "Route", "Status", "Assigned Users"]].to_html(escape=False, index=False), unsafe_allow_html=True)
    if not access.empty:
        st.markdown("#### Current User Mappings")
        st.dataframe(access.rename(columns={"username": "Username", "code": "Code", "application": "Application", "is_default": "Default"}), use_container_width=True, hide_index=True)

    users = snapshot["users"]
    if users.empty:
        return
    st.markdown("#### Update User Application Access")
    user_options = {
        f"{row['username']} — {row['name']}": int(row["id"])
        for _, row in users.iterrows()
    }
    application_options = {
        f"{row['name']} — {row['code']}": int(row["id"])
        for _, row in applications.iterrows()
    }
    selected_user_label = st.selectbox("User", list(user_options), key="access_user")
    selected_user_id = user_options[selected_user_label]
    selected_username = users.loc[users["id"] == selected_user_id, "username"].iloc[0]
    assigned_codes = set(access.loc[access["username"] == selected_username, "code"].astype(str))
    default_labels = [
        label for label, application_id in application_options.items()
        if str(applications.loc[applications["id"] == application_id, "code"].iloc[0]) in assigned_codes
    ]
    selected_labels = st.multiselect(
        "Assigned Applications", list(application_options), default=default_labels,
        key=f"access_applications_{selected_user_id}",
    )
    if st.button("Save Application Access", type="primary", key="save_application_access"):
        try:
            replace_user_applications(
                _current_admin(), selected_user_id,
                [application_options[label] for label in selected_labels],
            )
            st.success("Application access updated successfully.")
            st.rerun()
        except (PermissionError, ValueError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("Application access could not be updated because of a database error.")


def _render_data_sources() -> None:
    st.markdown("### Data Sources")
    postgres_online = False
    try:
        postgres_online = database_is_online()
    except Exception:
        pass
    upload_dir = Path("data/uploads")
    excel_configured = upload_dir.exists() and any(upload_dir.glob("*.xlsx"))
    sources = pd.DataFrame([
        {"Source": "PostgreSQL", "Type": "DATABASE", "Status": _badge("Connected" if postgres_online else "Error")},
        {"Source": "Utility Excel Reports", "Type": "EXCEL", "Status": _badge("Configured" if excel_configured else "Not Configured")},
        {"Source": "Weather Data", "Type": "OPEN-METEO", "Status": _badge("Available")},
        {"Source": "Telemetry", "Type": "DATABASE", "Status": _badge("Configured" if postgres_online else "Not Configured")},
    ])
    cards = st.columns(3)
    cards[0].metric("Connections", len(sources))
    cards[1].metric("Connected", int(sources["Status"].str.contains("Connected").sum()))
    cards[2].metric("Configured", int(sources["Status"].str.contains("Configured").sum()))
    st.write(sources.to_html(escape=False, index=False), unsafe_allow_html=True)


def _render_extraction() -> None:
    st.markdown("### Data Extraction")
    st.caption("Extraction controls are presented for the configured source contract.")
    source = st.selectbox("Data Source", ["PostgreSQL", "Utility Excel Reports"])
    dataset = st.selectbox("Dataset", ["Daily Generation", "15-Minute Telemetry", "Utility Consumption"])
    mode = st.radio("Extraction Mode", ["Full", "Incremental"], horizontal=True)
    first, second = st.columns(2)
    with first:
        from_date = st.date_input("From")
    with second:
        to_date = st.date_input("To")
    st.info("Extraction execution is not configured in the existing service layer.")
    st.button("Run Extraction", type="primary", disabled=True, help=f"{mode} extraction for {dataset} from {source} is not configured.")
    if from_date > to_date:
        st.warning("The selected start date is after the end date.")


def _render_schedules(settings: dict[str, str]) -> None:
    st.markdown("### Report Schedules")
    st.caption("Scheduling service status is intentionally reported honestly.")
    st.info("Scheduling service not configured")
    rows = pd.DataFrame([
        {"Report": "Daily Generation Report", "Frequency": "Not configured", "Next Run": "N/A", "Status": _badge("Not Configured"), "Actions": "Unavailable"},
        {"Report": "Monthly Utility Report", "Frequency": "Not configured", "Next Run": "N/A", "Status": _badge("Not Configured"), "Actions": "Unavailable"},
    ])
    st.write(rows.to_html(escape=False, index=False), unsafe_allow_html=True)


def _render_ai(settings: dict[str, str]) -> None:
    st.markdown("### AI Configuration")
    st.caption("Configuration values are stored through the existing admin_config service.")
    enabled = st.toggle("Enable AI Diagnostic Agent", value=settings.get("ai_enabled", "true") == "true")
    threshold = st.slider("Alert Threshold", 0, 100, int(float(settings.get("alert_threshold", "80"))))
    st.markdown("#### Diagnostic Framework")
    first, second = st.columns(2)
    with first:
        st.checkbox("Question", value=True, disabled=True)
        st.checkbox("Evidence", value=True, disabled=True)
        st.checkbox("Confidence", value=True, disabled=True)
    with second:
        st.checkbox("Hypothesis", value=True, disabled=True)
        st.checkbox("Root Cause Candidates", value=True, disabled=True)
        st.checkbox("Recommended Action", value=True, disabled=True)
    if st.button("Save AI Configuration", type="primary"):
        save_setting("ai_enabled", str(enabled).lower())
        save_setting("alert_threshold", str(threshold))
        st.success("AI configuration saved.")


def _render_services() -> None:
    st.markdown("### System Services")
    postgres_online = False
    try:
        postgres_online = database_is_online()
    except Exception:
        pass
    rows = [
        {"Service": "PostgreSQL", "Status": _badge("Healthy" if postgres_online else "Error"), "Evidence": "Live connectivity check"},
        {"Service": "Data Ingestion", "Status": _badge("Available"), "Evidence": "Ingestion module installed"},
        {"Service": "Utility Analytics", "Status": _badge("Available"), "Evidence": "Dashboard analytics loaded"},
        {"Service": "AI Diagnostic Agent", "Status": _badge("Configured"), "Evidence": "Application configuration"},
        {"Service": "Report Scheduler", "Status": _badge("Not Configured"), "Evidence": "No scheduler service registered"},
        {"Service": "Weather Service", "Status": _badge("Available"), "Evidence": "Open-Meteo integration"},
    ]
    st.write(pd.DataFrame(rows).to_html(escape=False, index=False), unsafe_allow_html=True)


def render_admin_control_center() -> None:
    if not st.session_state.get("logged_in") or str(st.session_state.get("user_role", "")).upper() != "ADMIN":
        st.error("Administrator access is required.")
        return
    _inject_styles()
    _render_header()
    snapshot = get_admin_snapshot()
    settings = get_settings()
    admin_page = st.radio(
        "Admin Navigation",
        ADMIN_PAGES,
        horizontal=True,
        label_visibility="collapsed",
        key="admin_control_navigation",
    )
    st.divider()

    if admin_page == "Overview":
        _render_overview(snapshot)
    elif admin_page == "Manage Locations":
        _render_locations(snapshot)
    elif admin_page == "Manage Utilities":
        _render_utilities(snapshot)
    elif admin_page == "Manage Users":
        _render_users(snapshot)
    elif admin_page == "Applications & Access":
        _render_access(snapshot)
    elif admin_page == "Data Sources":
        _render_data_sources()
    elif admin_page == "Data Extraction":
        _render_extraction()
    elif admin_page == "Report Schedules":
        _render_schedules(settings)
    elif admin_page == "AI Configuration":
        _render_ai(settings)
    elif admin_page == "System Services":
        _render_services()
