"""
Load asset version and component data from Ftrack (session + asset_id).

Pure logic - no UI, no DCC. Extracted from Houdini finput build_version_component_menus.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CachedData = Dict[str, Any]


def load_asset_version_component_data(
    session: Any,
    asset_id: str,
    force_refresh: bool = False,
) -> Optional[CachedData]:
    """
    Load versions and components for asset. Same logic as Houdini build_version_component_menus.

    Args:
        session: ftrack_api.Session
        asset_id: Ftrack asset ID
        force_refresh: If True, use query instead of relationship (fresh from server)

    Returns:
        Cached data dict with:
            version_info: [{"name": "v044", "id": "...", "version": 44}, ...]
            components_map: {version_id: [comp_id, ...]}
            components_file_types: {version_id: {comp_id: "sc"}}
            components_names: {version_id: {comp_id: "maya_part"}}
            asset_name: str
            asset_type: str
        Or None if failed.
    """
    if not session or not asset_id:
        logger.error("load_asset_version_component_data: session or asset_id missing.")
        return None

    try:
        if force_refresh:
            versions_query = (
                f'select id from AssetVersion where asset.id is "{asset_id}" '
                "order by version desc"
            )
            version_ids_result = session.query(versions_query).all()
            version_ids = [v["id"] for v in version_ids_result] if version_ids_result else []
        else:
            try:
                asset_entity = session.get("Asset", asset_id)
                if not asset_entity:
                    version_ids = []
                else:
                    versions_rel = asset_entity.get("versions", [])
                    if hasattr(versions_rel, "__iter__") and not isinstance(
                        versions_rel, (list, tuple)
                    ):
                        versions_list = list(versions_rel)
                    else:
                        versions_list = versions_rel or []
                    versions_list.sort(key=lambda v: v.get("version", 0), reverse=True)
                    version_ids = [v["id"] for v in versions_list]
            except Exception as e:
                logger.warning("Relationship failed, fallback to query: %s", e)
                versions_query = (
                    f'select id from AssetVersion where asset.id is "{asset_id}" '
                    "order by version desc"
                )
                version_ids_result = session.query(versions_query).all()
                version_ids = [v["id"] for v in version_ids_result] if version_ids_result else []

        if not version_ids:
            logger.warning("No versions found for asset %s", asset_id)
            return None

        versions_entities: List[Any] = []
        for vid in version_ids:
            try:
                v = session.get("AssetVersion", vid)
                if v:
                    versions_entities.append(v)
            except Exception as e:
                logger.warning("Failed to get version %s: %s", vid, e)

        if not versions_entities:
            return None

        if force_refresh:
            try:
                session.populate(versions_entities, "date, comment")
            except Exception as e:
                logger.warning("Failed to refresh version metadata: %s", e)

        try:
            session.populate(
                versions_entities,
                "components, components.name, components.id, components.file_type",
            )
        except Exception as e:
            logger.warning("Failed to populate components: %s", e)

        versions_entities.sort(key=lambda v: v.get("version", 0), reverse=True)
        versions = versions_entities

        version_info: List[Dict[str, Any]] = []
        for v in versions:
            ver_num = v.get("version", 0)
            version_info.append({
                "name": f"v{ver_num:03d}",
                "id": v["id"],
                "version": ver_num,
            })

        components_map: Dict[str, List[str]] = {}
        components_file_types: Dict[str, Dict[str, str]] = {}
        components_names: Dict[str, Dict[str, str]] = {}

        for v in versions:
            version_id = v["id"]
            components_map[version_id] = []
            components_file_types[version_id] = {}
            components_names[version_id] = {}

            for c in v.get("components", []) or []:
                comp_id = c["id"]
                comp_name = c.get("name", "")
                file_type = c.get("file_type", "")
                components_map[version_id].append(comp_id)
                components_file_types[version_id][comp_id] = file_type
                components_names[version_id][comp_id] = comp_name

            components_map[version_id] = sorted(
                components_map[version_id],
                key=lambda cid: (components_names[version_id].get(cid) or "").lower(),
            )

        asset_entity = versions[0].get("asset")
        asset_name = asset_entity.get("name", "") if asset_entity else ""
        asset_type = ""
        if asset_entity and asset_entity.get("type"):
            t = asset_entity["type"]
            asset_type = t.get("name", "") if hasattr(t, "get") else str(t)

        return {
            "version_info": version_info,
            "components_map": components_map,
            "components_file_types": components_file_types,
            "components_names": components_names,
            "asset_name": asset_name,
            "asset_type": asset_type,
        }
    except Exception as e:
        logger.error("load_asset_version_component_data failed: %s", e, exc_info=True)
        return None
