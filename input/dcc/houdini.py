"""
Houdini DCC adapter: full HDA callback API using input core.

Replaces finput for the new HDA. All logic self-contained, no finput dependency.
"""

from __future__ import annotations

import json
import logging
import socket
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ftrack_inout.input.dcc.houdini")


def _get_session():
    """Session from ftrack_inout.common."""
    try:
        from ftrack_inout.common.session_factory import get_shared_session
        return get_shared_session()
    except ImportError:
        return None


def _node_utils():
    from ftrack_houdini.ftrack_hou_utils import node_utils
    return node_utils


def _ftrack_utils():
    from ftrack_houdini.ftrack_hou_utils import ftrack_utils
    return ftrack_utils


def load_asset_version_data_for_houdini(
    session: Any,
    asset_id: str,
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """Load version/component cached data using input core."""
    if not session:
        return None
    from ftrack_inout.input.core import load_asset_version_component_data
    return load_asset_version_component_data(session, str(asset_id), force_refresh=force_refresh)


# --- build_version_component_menus ---

def build_version_component_menus(
    node: Any,
    asset_id: str,
    preserve_selection: bool = True,
    version_to_select_id: Optional[str] = None,
    component_to_select_name: Optional[str] = None,
    force_refresh: bool = False,
) -> bool:
    """Build version/component menus using input core."""
    import hou
    nu = _node_utils()
    if not node or not asset_id:
        logger.error("build_version_component_menus: node or asset_id is missing.")
        return False

    logger.info("Building version/component menus for asset %s", asset_id)
    nu.set_parm(node, "log", "Loading version data...")

    current_version_id = None
    if preserve_selection:
        vp = node.parm("version_menu")
        if vp:
            current_version_id = vp.evalAsString()

    try:
        session = _get_session()
        if not session:
            logger.error("Cannot build menus: Ftrack session not available.")
            return False

        cached_data = load_asset_version_data_for_houdini(
            session, asset_id, force_refresh=force_refresh
        )
        if not cached_data or not cached_data.get("version_info"):
            logger.warning("Input core failed or returned no data")
            nu.set_parm(node, "log", "ERROR: Input core unavailable or no versions.")
            return False

        version_info = cached_data["version_info"]
        node.setUserData("ftrack_asset_data", json.dumps(cached_data))
        logger.info("Cached data for %d versions", len(version_info))

        ptg = node.parmTemplateGroup()
        if ptg.find("version_menu"):
            ptg.remove("version_menu")
        if ptg.find("component_menu"):
            ptg.remove("component_menu")
        node.setParmTemplateGroup(ptg)
        ptg = node.parmTemplateGroup()

        comp_name_tpl = ptg.find("ComponentName")
        if comp_name_tpl:
            comp_name_tpl.setJoinWithNext(True)
            ptg.replace("ComponentName", comp_name_tpl)

        version_menu_items = [v["id"] for v in version_info]
        version_menu_labels = [v["name"] for v in version_info]
        version_menu = hou.MenuParmTemplate(
            "version_menu", "Version",
            menu_items=version_menu_items,
            menu_labels=version_menu_labels,
        )
        version_menu.setScriptCallback("hou.phm().ftrack_hda.applyVersionSelection(**kwargs)")
        version_menu.setScriptCallbackLanguage(hou.scriptLanguage.Python)
        version_menu.hideLabel(True)
        version_menu.setJoinWithNext(True)
        ptg.insertAfter(ptg.find("ComponentName"), version_menu)
        node.setParmTemplateGroup(ptg)

        version_to_select = None
        if version_to_select_id and version_to_select_id in version_menu_items:
            version_to_select = version_to_select_id
        elif preserve_selection and current_version_id and current_version_id in version_menu_items:
            version_to_select = current_version_id
        elif version_menu_items:
            version_to_select = version_info[0]["id"]
        if version_to_select:
            node.parm("version_menu").set(version_to_select)

        _apply_version_selection(node=node, component_to_select_name=component_to_select_name)

        asset_name = cached_data.get("asset_name", "")
        asset_type = cached_data.get("asset_type", "")
        nu.set_parm(node, "asset_id", asset_id)
        nu.set_parm(node, "asset_name", asset_name)
        nu.set_parm(node, "Type", asset_type)
        nu.set_parm(node, "log", "Loaded: %s (%d versions)" % (asset_name, len(version_info)))
        return True

    except Exception as e:
        logger.error("build_version_component_menus failed: %s", e, exc_info=True)
        nu.set_parm(node, "log", "ERROR: %s" % e)
        return False


def _apply_version_selection(
    node: Any,
    component_to_select_name: Optional[str] = None,
) -> None:
    """Build component menu from cached_data using input.core."""
    import hou
    from ftrack_inout.input.core import get_component_menu_data, resolve_component_to_select

    json_str = node.userData("ftrack_asset_data")
    cached_data = json.loads(json_str) if json_str else {}
    if not cached_data:
        return
    ver_menu = node.parm("version_menu")
    if not ver_menu:
        return
    version_id = ver_menu.evalAsString()
    items, labels = get_component_menu_data(cached_data, version_id)
    comp_parm = node.parm("component_menu")
    prev_comp_id = comp_parm.evalAsString() if comp_parm else None
    to_select = resolve_component_to_select(
        cached_data, version_id,
        component_to_select_name=component_to_select_name,
        previous_comp_id=prev_comp_id or None,
    )
    nu = _node_utils()
    ptg = node.parmTemplateGroup()
    if ptg.find("component_menu"):
        ptg.remove("component_menu")
    node.setParmTemplateGroup(ptg)
    ptg = node.parmTemplateGroup()
    if not items:
        return
    comp_menu = hou.MenuParmTemplate("component_menu", "Component", menu_items=items, menu_labels=labels)
    comp_menu.setScriptCallback("hou.phm().ftrack_hda.applyCompSelection(**kwargs)")
    comp_menu.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    comp_menu.hideLabel(True)
    ptg.insertAfter(ptg.find("version_menu"), comp_menu)
    node.setParmTemplateGroup(ptg)
    idx = items.index(to_select) if to_select in items else 0
    node.parm("component_menu").set(items[idx])
    applyCompSelection(node=node)


def applyVersionSelection(**kwargs) -> None:
    """Version changed — rebuild component menu."""
    import hou
    node = kwargs.get("node") or hou.pwd()
    comp_name = kwargs.get("component_to_select_name")
    _apply_version_selection(node=node, component_to_select_name=comp_name)


def _update_version_menu_indicators(node: Any) -> None:
    """Update version menu labels with (*) for matching components."""
    from ftrack_inout.input.core import compute_version_labels_with_indicators

    json_str = node.userData("ftrack_asset_data")
    cached_data = json.loads(json_str) if json_str else {}
    if not cached_data or not cached_data.get("version_info"):
        return
    comp_menu = node.parm("component_menu")
    ver_menu = node.parm("version_menu")
    if not comp_menu or not ver_menu:
        return
    selected_comp_id = comp_menu.evalAsString()
    current_version_id = ver_menu.evalAsString()
    if not selected_comp_id:
        return

    labels = compute_version_labels_with_indicators(
        cached_data, selected_comp_id, current_version_id
    )
    ptg = node.parmTemplateGroup()
    version_menu_template = ptg.find("version_menu")
    if version_menu_template and labels:
        version_menu_template.setMenuLabels(labels)
        ptg.replace("version_menu", version_menu_template)
        node.setParmTemplateGroup(ptg)


def applyCompSelection(**kwargs) -> None:
    """Component selected — load data and update indicators."""
    import hou
    nu = _node_utils()
    node = kwargs.get("node")
    if not node:
        node = hou.pwd()

    nu.set_parm(node, "log", "Applying component...")
    try:
        session = _get_session()
        comp_menu = node.parm("component_menu")
        ver_menu = node.parm("version_menu")
        if not comp_menu or not ver_menu:
            nu.set_parm(node, "log", "ERROR: Menus not found. Re-select asset.")
            return

        comp_id = comp_menu.evalAsString()
        ver_id = ver_menu.evalAsString()
        logger.info("Applying Version ID: %s, Component ID: %s", ver_id, comp_id)

        component = session.get("Component", comp_id)
        if not component:
            raise Exception("Component ID '%s' not found." % comp_id)

        version = component["version"]
        parms_to_set = {
            "AssetVersion": version["id"],
            "ComponentName": component["name"],
            "componentid": component["id"],
            "variables": json.dumps({"FTRACK_COMPONENT_ID": component["id"]}),
            "log": "Applied: v%03d / %s" % (version["version"], component["name"]),
            "__ftrack_used_CompId": component["id"],
        }
        nu.set_multiple_parms(node, parms_to_set)
        logger.info("Successfully applied component data to node.")
        _update_version_menu_indicators(node)

    except Exception as e:
        logger.error("Failed to apply component: %s", e, exc_info=True)
        nu.set_parm(node, "log", "ERROR: %s" % e)


# --- get_data ---

def get_data(**kwargs) -> None:
    """Fetch data for selected AssetVersion and populate HDA parameters."""
    import hou
    import ftrack_api
    nu = _node_utils()
    fu = _ftrack_utils()
    node = kwargs.get("node")
    if not node:
        return

    asset_version_id = nu.get_parm_evaluated_string(node, "AssetVersion")
    comp_name = nu.get_parm_evaluated_string(node, "ComponentName")
    comp_id_only = None
    try:
        comp_id_only = nu.get_parm_evaluated_string(node, "componentid")
    except Exception:
        pass

    logger.info("get_data: AssetVersion=%s, Component=%s, componentid=%s",
                asset_version_id, comp_name, comp_id_only or "")

    if not asset_version_id and comp_id_only:
        logger.info("get_data: AssetVersion empty, falling back to get_fromcomp")
        try:
            get_fromcomp(node=node)
        except Exception as e:
            logger.error("get_data fallback via get_fromcomp failed: %s", e, exc_info=True)
            nu.set_parm(node, "log", "ERROR: get_fromcomp failed: %s" % e)
        return

    if not asset_version_id:
        nu.set_parm(node, "log", "ERROR: AssetVersion is required.")
        return

    asset_version_only_mode = not comp_name
    asset_version_entity = fu.get_entity("AssetVersion", asset_version_id)
    if not asset_version_entity:
        nu.set_parm(node, "log", "ERROR: Invalid AssetVersion ID.")
        return

    nu.set_parm(node, "__ftrack_AssetVersion", asset_version_id)
    asset_entity = asset_version_entity["asset"]
    asset_type = asset_entity["type"]["name"]
    asset_id = asset_entity["id"]
    asset_name = asset_entity["name"]
    current_asset_id = nu.get_parm_evaluated_string(node, "asset_id")
    is_refresh = (current_asset_id == asset_id)

    if asset_version_only_mode:
        parms_to_set = {
            "Type": asset_type,
            "asset_id": asset_id,
            "asset_name": asset_name,
            "file_path": "",
            "componentid": "",
            "ComponentName": "",
        }
        project_name = asset_entity["parent"]["project"]["name"]
        context_path = "{}:{}:{}".format(
            project_name,
            ":".join(x["name"] for x in asset_entity["ancestors"]),
            asset_entity["name"],
        )
        variables = {
            "ASSET_NAME": str(asset_entity["name"]),
            "ASSET_TYPE_NAME": str(asset_type),
            "ASSET_ID": str(asset_entity["id"]),
            "VERSION_NUMBER": str(int(asset_version_entity["version"])),
            "REFERENCE_OBJECT": "",
            "CONTEXT_PATH": str(context_path),
            "COMPONENT_NAME": "",
            "COMPONENT_ID": "",
            "COMPONENT_PATH": "",
        }
        nu.set_multiple_parms(node, parms_to_set)
        nu.set_parm(node, "metadict", {})
        nu.set_parm(node, "variables", variables)
    else:
        session = fu.get_session()
        if not session:
            logger.error("Ftrack session not available.")
            return
        try:
            location = session.pick_location()
            if not location:
                raise ftrack_api.exception.LocationError("Could not pick a location.")
        except Exception as e:
            logger.error("Ftrack location error: %s", e, exc_info=True)
            nu.set_parm(node, "log", "ERROR: Ftrack location error.")
            return

        try:
            session.populate([asset_version_entity], "components, components.name, components.id")
        except Exception:
            pass
        comp_id_param = nu.get_parm_evaluated_string(node, "componentid")
        selected_component = None
        for c in asset_version_entity.get("components") or []:
            if c["id"] == comp_id_param:
                selected_component = c
                break
        if not selected_component and comp_name:
            for c in asset_version_entity.get("components") or []:
                if (c.get("name") or "").lower() == comp_name.lower():
                    selected_component = c
                    break

        if not selected_component:
            logger.warning("Component not found")
            nu.set_parm(node, "log", "WARN: Component not found.")
            return

        availability = location.get_component_availability(selected_component)
        parms_to_set = {
            "componentid": selected_component["id"],
            "ComponentName": selected_component["name"],
            "Type": asset_type,
            "asset_id": asset_id,
            "asset_name": asset_name,
        }
        meta = dict(selected_component.get("metadata") or {})
        project_name = asset_entity["parent"]["project"]["name"]
        context_path = "{}:{}:{}".format(
            project_name,
            ":".join(x["name"] for x in asset_entity["ancestors"]),
            asset_entity["name"],
        )
        variables = {
            "ASSET_NAME": str(asset_entity["name"]),
            "ASSET_TYPE_NAME": str(asset_type),
            "ASSET_ID": str(asset_entity["id"]),
            "VERSION_NUMBER": str(int(asset_version_entity["version"])),
            "REFERENCE_OBJECT": "",
            "CONTEXT_PATH": str(context_path),
            "COMPONENT_NAME": str(selected_component["name"]),
            "COMPONENT_ID": str(selected_component["id"]),
            "COMPONENT_PATH": "",
        }
        component_path = ""
        if availability == 100.0:
            try:
                from ftrack_inout.input.core import resolve_component_path
                component_path = resolve_component_path(
                    session, selected_component, location=location
                )
            except ValueError:
                component_path = ""
            if component_path:
                parms_to_set["file_path"] = component_path
                variables["COMPONENT_PATH"] = component_path
            else:
                parms_to_set["file_path"] = ""
        else:
            parms_to_set["file_path"] = ""

        nu.set_multiple_parms(node, parms_to_set)
        nu.set_parm(node, "metadict", meta)
        nu.set_parm(node, "variables", variables)
        nu.set_parm(node, "__ftrack_used_CompId", selected_component["id"])

        try:
            if node.parm("transfer_ready"):
                node.parm("transfer_ready").set(0)
            if node.parm("transfer_from_id"):
                node.parm("transfer_from_id").set("")
            if node.parm("transfer_to_id"):
                node.parm("transfer_to_id").set("")
            if availability < 100.0 or (availability == 100.0 and not component_path):
                src_loc_id = ""
                try:
                    all_locations = fu.get_session().query("Location").all()
                except Exception:
                    all_locations = []
                current_location = location
                for loc in all_locations or []:
                    try:
                        if current_location and loc["id"] == current_location["id"]:
                            continue
                        src_av = loc.get_component_availability(selected_component)
                        if src_av and src_av > 0.0:
                            src_loc_id = loc["id"]
                            break
                    except Exception:
                        continue
                if src_loc_id:
                    try:
                        if node.parm("transfer_ready"):
                            node.parm("transfer_ready").set(1)
                        if node.parm("transfer_from_id"):
                            node.parm("transfer_from_id").set(src_loc_id)
                        if node.parm("transfer_to_id") and location:
                            node.parm("transfer_to_id").set(location["id"])
                    except Exception:
                        pass
        except Exception:
            pass

    success = build_version_component_menus(
        node,
        asset_id,
        preserve_selection=is_refresh,
        version_to_select_id=asset_version_entity["id"],
        component_to_select_name=comp_name if not asset_version_only_mode else None,
        force_refresh=True,
    )

    if success:
        action = "Refreshed" if is_refresh else "Loaded"
        if not asset_version_only_mode:
            nu.set_parm(node, "log", "%s: %s (%s)" % (action, asset_name, comp_name))
        else:
            selected_comp_id = node.parm("component_menu").evalAsString()
            json_string = node.userData("ftrack_asset_data")
            cached_data = json.loads(json_string) if json_string else {}
            ver_id = node.parm("version_menu").evalAsString() if node.parm("version_menu") else None
            comp_name_map = (cached_data.get("components_names") or {}).get(ver_id, {}) if ver_id else {}
            final_comp_name = comp_name_map.get(selected_comp_id, selected_comp_id)
            nu.set_parm(node, "log", "Created menus for: %s (auto-selected: %s)" % (asset_name, final_comp_name))
    else:
        logger.warning("get_data: Failed to build version/component menus")


# --- get_fromcomp ---

def get_fromcomp(**kwargs) -> None:
    """Load from component ID — populate params and build menus."""
    nu = _node_utils()
    fu = _ftrack_utils()
    node = kwargs.get("node")
    if not node:
        return

    comp_id = nu.get_parm_evaluated_string(node, "componentid")
    if not comp_id:
        return

    comp = fu.get_entity("Component", comp_id)
    if not comp:
        logger.error("Could not find Component %s", comp_id)
        return

    comp_name = comp["name"]
    asset_version = comp["version"]
    asset_version_id = asset_version["id"]
    asset_type = asset_version["asset"]["type"]["name"]
    asset_id = asset_version["asset"]["id"]
    asset_name = asset_version["asset"]["name"]

    current_asset_id = nu.get_parm_evaluated_string(node, "asset_id")
    is_refresh = (current_asset_id == asset_id)

    parms_to_set = {
        "ComponentName": comp_name,
        "AssetVersion": asset_version_id,
        "Type": asset_type,
        "componentid": comp_id,
        "__ftrack_used_CompId": comp_id,
        "asset_id": asset_id,
        "asset_name": asset_name,
    }
    nu.set_multiple_parms(node, parms_to_set)

    success = build_version_component_menus(
        node,
        asset_id,
        preserve_selection=is_refresh,
        version_to_select_id=asset_version_id,
        component_to_select_name=comp_name,
    )

    if success:
        action = "Refreshed" if is_refresh else "Loaded"
        nu.set_parm(node, "log", "%s: %s (%s)" % (action, asset_name, comp_name))
    else:
        logger.warning("get_fromcomp: Failed to build version/component menus")


# --- create_node ---

def create_node(**kwargs) -> None:
    """Create internal node network from selected component."""
    from ftrack_houdini.ftrack_hou_utils.template_utils import TemplateManager, create_node_from_template

    nu = _node_utils()
    fu = _ftrack_utils()
    hda_node = kwargs.get("node")
    if not hda_node:
        return

    try:
        tm = TemplateManager()
    except Exception as e:
        logger.error("TemplateManager init failed: %s", e)
        return

    component_id = nu.get_parm_evaluated_string(hda_node, "componentid")
    if not component_id:
        import hou
        hou.ui.displayMessage("Please select a component from the menu before creating.", title="Ftrack Loader")
        return

    component_entity = fu.get_entity("Component", component_id)
    if not component_entity:
        import hou
        hou.ui.displayMessage("Could not find component %s in Ftrack." % component_id, title="Ftrack Loader Error")
        return

    version = component_entity["version"]
    asset = version["asset"]
    asset_type = asset["type"]["name"]
    component_name = component_entity["name"]
    file_format = (component_entity.get("file_type") or "").replace(".", "")

    # Use path already on node from get_data if present; else resolve
    component_path = (nu.get_parm_evaluated_string(hda_node, "file_path") or "").strip()
    if not component_path:
        try:
            from ftrack_inout.input.core import resolve_component_path
            session = fu.get_session()
            component_path = resolve_component_path(session, component_entity) if session else ""
        except ValueError:
            component_path = ""
    if not component_path:
        import hou
        hou.ui.displayMessage("Could not determine file path for component.", title="Ftrack Loader Error")
        return

    nu.set_parm(hda_node, "file_path", component_path)

    subnet_node = create_node_from_template(
        template_manager=tm,
        hda_node=hda_node,
        asset_type=asset_type,
        component_name=component_name,
        file_format=file_format,
    )

    import hou
    if subnet_node:
        subnet_pos = subnet_node.position()
        hou.ui.displayMessage(
            "Successfully created loader: %s\nLocation: %s\nPosition: (%.1f, %.1f)" % (
                subnet_node.name(), subnet_node.path(), subnet_pos.x(), subnet_pos.y()
            ),
            title="Ftrack Loader - Success",
        )
    else:
        template_check = tm.find_matching_template(asset_type, component_name, file_format)
        if not template_check:
            hou.ui.displayMessage(
                "No matching template for:\nAsset Type: %s\nComponent: %s\nFormat: %s" % (
                    asset_type, component_name, file_format
                ),
                title="Ftrack Loader Error",
            )
        else:
            hou.ui.displayMessage("An unexpected error occurred during node creation.", title="Ftrack Loader Error")


# --- transferToLocal ---

_transfer_dialog_instance = None


def _ensure_transfer_dialog(session: Any) -> Any:
    global _transfer_dialog_instance
    try:
        from ftrack_inout.browser.transfer_status_widget import get_transfer_dialog
        if _transfer_dialog_instance is None:
            _transfer_dialog_instance = get_transfer_dialog(session)
        return _transfer_dialog_instance
    except Exception as e:
        logger.warning("Transfer dialog not available: %s", e)
        return None


def transferToLocal(**kwargs) -> None:
    """Start transfer of selected component."""
    import hou
    nu = _node_utils()
    fu = _ftrack_utils()
    node = kwargs.get("node") or hou.pwd()

    try:
        comp_id = node.parm("componentid").eval() if node.parm("componentid") else ""
        ready = int(node.parm("transfer_ready").eval()) if node.parm("transfer_ready") else 0
        from_id = node.parm("transfer_from_id").eval() if node.parm("transfer_from_id") else ""
        to_id = node.parm("transfer_to_id").eval() if node.parm("transfer_to_id") else ""
        comp_name = node.parm("ComponentName").eval() if node.parm("ComponentName") else ""
    except Exception:
        comp_id, ready, from_id, to_id, comp_name = "", 0, "", "", ""

    if not comp_id:
        nu.set_parm(node, "log", "Transfer: No component selected.")
        return
    if not ready or not from_id or not to_id:
        nu.set_parm(node, "log", "Transfer: Not ready (check availability/locations).")
        return

    selection_entities = [{"entityType": "Component", "entityId": comp_id}]

    try:
        session = fu.get_session()
        if not session:
            nu.set_parm(node, "log", "Transfer: Failed to get ftrack session.")
            return

        user = session.query('User where username is "%s"' % session.api_user).one()
        user_id = user["id"]

        from_loc_name, to_loc_name = from_id, to_id
        try:
            from_loc = session.query('select id, name, label from Location where id is "%s"' % from_id).first()
            if from_loc:
                from_loc_name = from_loc.get("label") or from_loc.get("name") or from_id
            to_loc = session.query('select id, name, label from Location where id is "%s"' % to_id).first()
            if to_loc:
                to_loc_name = to_loc.get("label") or to_loc.get("name") or to_id
        except Exception:
            pass

        from ftrack_api.event.base import Event

        job_meta = {
            "tag": "mroya_transfer",
            "description": "Transfer from %s to %s (Houdini input)" % (from_loc_name, to_loc_name),
            "component_label": comp_name or "component",
            "from_location_id": from_id,
            "to_location_id": to_id,
            "to_location_name": to_loc_name,
            "from_location_type": "unknown",
            "to_location_type": "unknown",
            "total_size_bytes": 0,
        }
        job = session.create("Job", {
            "user_id": user_id,
            "status": "running",
            "data": json.dumps(job_meta),
        })
        session.commit()
        job_id = job["id"]

        payload = {
            "job_id": job_id,
            "user_id": user_id,
            "from_location_id": from_id,
            "to_location_id": to_id,
            "selection": list(selection_entities),
            "ignore_component_not_in_location": False,
            "ignore_location_errors": False,
        }
        current_hostname = socket.gethostname().lower()
        current_username = session.api_user or ""
        event = Event(
            topic="mroya.transfer.request",
            data=payload,
            source={"hostname": current_hostname, "user": {"username": current_username}},
        )
        try:
            session.event_hub.connect()
        except Exception:
            pass
        session.event_hub.publish(event, on_error="ignore")

        nu.set_parm(node, "log", "Transfer started: Job %s" % job_id)

        dialog = _ensure_transfer_dialog(session)
        if dialog:
            try:
                comp_display = comp_name or "component"
                try:
                    from ftrack_inout.common.path_from_project import get_component_display_path
                    comp_display = get_component_display_path(session, str(comp_id)) or comp_display
                except Exception:
                    pass
                dialog.add_job({"id": job_id, "status": "running"}, comp_display, to_loc_name, comp_id)
            except Exception as e:
                logger.warning("Failed to add job to dialog: %s", e)

    except Exception as e:
        logger.error("Transfer error: %s", e, exc_info=True)
        nu.set_parm(node, "log", "Transfer failed: %s" % e)


# --- toggle_subscribe_updates ---

def toggle_subscribe_updates(**kwargs) -> None:
    """Subscribe/unsubscribe to asset updates."""
    import hou
    nu = _node_utils()
    node = kwargs.get("node")
    if not node:
        return

    try:
        subscribe = node.parm("subscribe_updates")
        if not subscribe:
            return
        is_subscribed = subscribe.eval()

        component_id = nu.get_parm_evaluated_string(node, "componentid")
        if not component_id:
            nu.set_parm(node, "log", "Select a component first before subscribing")
            subscribe.set(0)
            return

        session = _get_session()
        if not session:
            return

        component = session.get("Component", component_id)
        if not component:
            return

        version = component["version"]
        asset = version["asset"]

        target_location_id = None
        target_location_name = None
        try:
            location = session.pick_location()
            if location:
                target_location_id = location["id"]
                target_location_name = location["name"]
        except Exception:
            pass

        scene_path = hou.hipFile.path()
        hostname = socket.gethostname().lower()

        if is_subscribed:
            try:
                session.event_hub.connect()
            except Exception:
                pass
            current_username = getattr(session, "api_user", None) or ""
            from ftrack_api.event.base import Event
            event = Event(
                topic="mroya.asset.watch",
                data={
                    "asset_id": asset["id"],
                    "asset_name": asset["name"],
                    "component_name": component["name"],
                    "component_id": component_id,
                    "target_location_id": target_location_id,
                    "target_location_name": target_location_name,
                    "current_version_id": version["id"],
                    "current_version_number": version["version"],
                    "source_dcc": "houdini",
                    "scene_path": scene_path,
                    "update_action": "wait_location",
                    "notify_dcc": True,
                },
                source={"hostname": hostname, "user": {"username": current_username}},
            )
            session.event_hub.publish(event, on_error="ignore")
            try:
                from ftrack_houdini.asset_update_listener import color_node_subscribed
                color_node_subscribed(node)
            except Exception:
                pass
            nu.set_parm(node, "log", "Subscribed to updates: %s/%s" % (asset["name"], component["name"]))
        else:
            try:
                session.event_hub.connect()
            except Exception:
                pass
            current_username = getattr(session, "api_user", None) or ""
            from ftrack_api.event.base import Event
            event = Event(
                topic="mroya.asset.unwatch",
                data={"asset_id": asset["id"], "component_name": component["name"]},
                source={"hostname": hostname, "user": {"username": current_username}},
            )
            session.event_hub.publish(event, on_error="ignore")
            try:
                from ftrack_houdini.asset_update_listener import color_node_default
                color_node_default(node)
            except Exception:
                pass
            nu.set_parm(node, "log", "Unsubscribed from %s/%s" % (asset["name"], component["name"]))

    except Exception as e:
        logger.error("toggle_subscribe_updates error: %s", e, exc_info=True)
        nu.set_parm(node, "log", "Subscribe error: %s" % e)


# --- cleanUi / restore_base_interface ---

def create_base_interface(**kwargs) -> Any:
    """Create base interface from HDA definition."""
    import hou
    node = kwargs.get("node")
    if not node:
        return None
    hda_ptg = node.type().definition().parmTemplateGroup()
    ptg = hou.ParmTemplateGroup()
    for parm_template in hda_ptg.parmTemplates():
        ptg.append(parm_template)
    return ptg


def restore_base_interface(**kwargs) -> bool:
    """Restore base interface, preserving key params."""
    nu = _node_utils()
    node = kwargs.get("node")
    if not node:
        logger.warning("restore_base_interface called without a node.")
        return False
    try:
        params_to_preserve = [
            "task_Id", "assets", "asset_id", "asset_name", "Type",
            "AssetVersion", "ComponentName", "componentid",
            "file_path", "test", "metadict", "variables",
        ]
        saved_values = {name: node.parm(name).eval() for name in params_to_preserve if node.parm(name)}
        base_ptg = create_base_interface(**kwargs)
        if base_ptg:
            node.setParmTemplateGroup(base_ptg)
            nu.set_multiple_parms(node, saved_values)
            node.setUserData("ftrack_asset_data", "{}")
            logger.info("Base interface restored for %s", node.name())
            return True
        return False
    except Exception as e:
        logger.error("Failed to restore base interface: %s", e, exc_info=True)
        return False


def restore_interface(**kwargs) -> bool:
    """Wrapper for compatibility."""
    return restore_base_interface(**kwargs)


def cleanUi(**kwargs) -> None:
    """Clean UI — restore to base state."""
    restore_base_interface(**kwargs)


def onCreated(**kwargs) -> None:
    """Called when node is created."""
    restore_base_interface(**kwargs)


# --- accept_update ---

def accept_update(**kwargs) -> None:
    """Accept pending update from Asset Watcher."""
    import hou
    nu = _node_utils()
    node = kwargs.get("node") or hou.pwd()
    try:
        from ftrack_houdini.asset_update_listener import accept_update as _accept_update
        _accept_update(node=node)
    except Exception as e:
        logger.error("accept_update error: %s", e, exc_info=True)
        nu.set_parm(node, "log", "Accept update error: %s" % e)
