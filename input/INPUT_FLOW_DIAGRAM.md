# Input Node Flow — Ftrack API call optimization

## Block diagram: User actions and API calls

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           INPUT NODE FLOW (Core path)                            │
└─────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────┐
  │ User: enters     │
  │ Asset Version ID │
  │ or Component Id  │
  └────────┬─────────┘
           │
           ▼
  ┌────────────────────────────────────────────────────────────────────────────────┐
  │ 1. LOAD VERSION MENU (asset_id known)                                           │
  │    load_asset_version_component_data(session, asset_id, force_refresh=False)    │
  └────────────────────────────────────────────────────────────────────────────────┘
           │
           │  force_refresh=False (default):
           │  ┌─────────────────────────────────────────────────────────────────────┐
           │  │ session.get("Asset", asset_id)         [1 call - cache]              │
           │  │   → asset["versions"] (relationship)   [0 calls - already loaded]    │
           │  │ session.get("AssetVersion", vid) x N   [N calls - uses cache]        │
           │  │ session.populate(versions, "components,...") [1 batch - fetch comps] │
           │  └─────────────────────────────────────────────────────────────────────┘
           │
           │  force_refresh=True:
           │  ┌─────────────────────────────────────────────────────────────────────┐
           │  │ session.query("AssetVersion where asset.id=...") [1 query]           │
           │  │ session.get("AssetVersion", vid) x N   [N - from server if not cache]│
           │  │ session.populate(versions, "date, comment") [1 - refresh metadata]   │
           │  │ session.populate(versions, "components,...") [1 - fetch components]  │
           │  └─────────────────────────────────────────────────────────────────────┘
           │
           ▼
  ┌────────────────────────────┐
  │ cached_data in memory      │
  │ (version_info, components_ │
  │  map, names, file_types)   │
  └────────────┬───────────────┘
               │
     ┌─────────┴─────────┬─────────────────────┬──────────────────────────┐
     │                   │                     │                          │
     ▼                   ▼                     ▼                          ▼
┌─────────────┐  ┌───────────────┐  ┌──────────────────────┐  ┌────────────────────┐
│ Version menu│  │ Component menu│  │ (*) indicators       │  │ Path resolution    │
│ (labels)    │  │ (items,labels)│  │ version labels       │  │ (file_path)        │
└─────────────┘  └───────────────┘  └──────────────────────┘  └────────────────────┘
     │                   │                     │                          │
     │ NO API            │ NO API              │ NO API                   │ API
     │ (from cache)      │ get_component_menu  │ compute_version_labels   │
     │                   │ _data(cached_data)  │ _with_indicators(cache)  │
     │                   │                     │                          │
     │                   │                     │                          ▼
     │                   │                     │              ┌───────────────────────┐
     │                   │                     │              │ resolve_component_   │
     │                   │                     │              │ path(session, comp)  │
     │                   │                     │              │   OR                 │
     │                   │                     │              │ get_component_       │
     │                   │                     │              │ location_info(comp_id)│
     │                   │                     │              │                      │
     │                   │                     │              │ session.pick_location│
     │                   │                     │              │ location.get_        │
     │                   │                     │              │ filesystem_path(comp)│
     │                   │                     │              └───────────────────────┘
     │                   │                     │
     └───────────────────┴─────────────────────┴──────────────────────────────────────
                                    │
                                    │ User switches Version in combo
                                    │
                                    ▼
                         ┌──────────────────────────────────┐
                         │ _populate_component_menu_combo    │
                         │   get_component_menu_data(cache)  │
                         │   resolve_component_to_select()   │
                         │   NO API CALLS (all from cache)   │
                         └──────────────────────────────────┘
                                    │
                                    │ User selects Component
                                    │
                                    ▼
                         ┌──────────────────────────────────┐
                         │ _update_version_menu_indicators   │
                         │   compute_version_labels_         │
                         │   with_indicators(cache)          │
                         │   NO API CALLS                    │
                         └──────────────────────────────────┘
                                    │
                                    │ User clicks "get from assetver"
                                    │
                                    ▼
                         ┌──────────────────────────────────┐
                         │ _resolve_path_for_current_component│
                         │   get_component_location_info()   │
                         │   1 call: pick_location +         │
                         │   get_component_availability +    │
                         │   get_filesystem_path             │
                         └──────────────────────────────────┘
```

## API calls summary

| Action                         | Core path (cached)                     | Legacy path (no cache)                         |
|--------------------------------|----------------------------------------|-----------------------------------------------|
| Load version menu (asset_id)   | 1 get(Asset) + N get(Version) + 1 populate | get_versions_for_asset (1 query) + N x get_components_for_version (N queries) |
| Switch version in combo        | 0 calls (from cache)                   | N calls (get_components_for_version per version) |
| Switch component in combo      | 0 calls (labels from cache)            | 0 calls (labels from _version_components_cache) |
| Get from assetver (path)       | 1 call (pick_location + path)          | 1 call (same)                                  |

## Optimization points

1. **Single batch load** — `load_asset_version_component_data` loads all versions + components in one populate. No per-version queries.

2. **Relationship cache** — `force_refresh=False` uses `asset["versions"]` (already in session cache from previous queries). Avoids redundant query.

3. **Cached data reuse** — Version labels, component menu, (*) indicators all derived from `cached_data`. Zero API when user switches version/component.

4. **Path = only network hit** — Path resolution is the only place we hit API after initial load (pick_location, get_filesystem_path). Could be optimized with location caching.

5. **Legacy fallback** — When core fails, legacy API does `get_versions_for_asset` + `get_components_for_version(version_id)` for each version when building menu — N+1 pattern.
