#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Quick performance diagnostics for ftrack browser

This script can be called directly from browser to check
current state of caching system.
"""

import time
import logging

logger = logging.getLogger(__name__)

def quick_performance_check(api_client=None, session=None):
    """
    Quick performance check for caching system
    
    Args:
        api_client: API client instance (if available)
        session: ftrack session (if available)
    """
    
    print("\n[SEARCH] QUICK PERFORMANCE DIAGNOSTICS")
    print("=" * 50)
    
    # Determine what we have
    if api_client:
        session = getattr(api_client, 'session', session)
        print("[OK] API client provided")
    elif session:
        print("[OK] Session provided")
    else:
        print("[FAIL] No API client or session for testing")
        return None
    
    if not session:
        print("[FAIL] Session not available")
        return None
    
    results = {
        'cache_type': 'unknown',
        'access_times': [],
        'projects_load_time': 0,
        'cache_layers': [],
        'performance_rating': 'unknown'
    }
    
    try:
        # === CACHE ANALYSIS ===
        
        print("\n🏗 CACHE ARCHITECTURE ANALYSIS:")
        
        cache = session.cache
        cache_type = type(cache).__name__
        results['cache_type'] = cache_type
        print(f"   Cache type: {cache_type}")
        
        # Analyze LayeredCache
        if hasattr(cache, '_caches'):
            caches_list = getattr(cache, '_caches', [])
            print(f"   Layers in LayeredCache: {len(caches_list)}")
            
            for i, cache_layer in enumerate(caches_list):
                layer_type = type(cache_layer).__name__
                results['cache_layers'].append(layer_type)
                print(f"     Layer {i}: {layer_type}")
        
        # === PROJECT LOAD TEST ===
        
        print("\n[CLIP] PROJECT LOAD TEST:")
        
        projects_start = time.time()
        try:
            if api_client and hasattr(api_client, 'get_projects'):
                projects = api_client.get_projects()
            else:
                projects = session.query('Project where status is "active"').all()
            
            projects_time = (time.time() - projects_start) * 1000
            results['projects_load_time'] = projects_time
            
            print(f"   ⏱  Load time: {projects_time:.1f}ms")
            print(f"   📦 Projects found: {len(projects)}")
            
            if projects_time < 100:
                print("   [OK] Fast load")
            elif projects_time < 500:
                print("   [WARN]  Slow load")
            else:
                print("   [FAIL] Very slow load")
                
        except Exception as e:
            print(f"   [FAIL] Error loading projects: {e}")
            projects = []
        
        # === CACHE ACCESS TEST ===
        
        if projects:
            print("\n🧪 CACHED DATA ACCESS TEST:")
            
            test_project = projects[0]
            project_id = test_project['id']
            
            # Multiple accesses to same object
            access_times = []
            for i in range(3):
                access_start = time.time()
                project = session.get('Project', project_id)
                access_time = (time.time() - access_start) * 1000
                access_times.append(access_time)
                print(f"   Attempt {i+1}: {access_time:.2f}ms")
            
            results['access_times'] = access_times
            avg_access = sum(access_times) / len(access_times)
            
            print(f"   [STATS] Average time: {avg_access:.2f}ms")
            
            # Performance rating
            if avg_access < 1.0:
                performance = "excellent"
                print("   [LAUNCH] EXCELLENT: Instant access!")
            elif avg_access < 5.0:
                performance = "good"
                print("   [OK] GOOD: Fast access")
            elif avg_access < 20.0:
                performance = "slow"
                print("   [WARN]  SLOW: Optimization required")
            else:
                performance = "very_slow"
                print("   [FAIL] VERY SLOW: Serious problems!")
            
            results['performance_rating'] = performance
        
        # === RECOMMENDATIONS ===
        
        print("\n💡 RECOMMENDATIONS:")
        
        if results['performance_rating'] == 'excellent':
            print("   🎉 System is working optimally!")
        elif results['performance_rating'] == 'good':
            print("   [OK] System is working well")
        elif results['performance_rating'] == 'slow':
            print("   [WARN]  Recommended:")
            print("     - Check cache settings")
            print("     - Clear cache: session.cache.clear()")
            print("     - Restart browser")
        elif results['performance_rating'] == 'very_slow':
            print("   [FAIL] CRITICAL PROBLEMS:")
            print("     - Cache is not working correctly")
            print("     - MemoryCache may be missing")
            print("     - System recovery required")
        
        # Check for our components
        has_memory_wrapper = any('MemoryCacheWrapper' in layer for layer in results['cache_layers'])
        has_logging_wrapper = any('LoggingCacheWrapper' in layer for layer in results['cache_layers'])
        
        if not has_memory_wrapper:
            print("   [WARN]  MemoryCacheWrapper missing in cache")
        if not has_logging_wrapper:
            print("   [WARN]  LoggingCacheWrapper missing in cache")
        
    except Exception as e:
        print(f"[FAIL] Diagnostic error: {e}")
        import traceback
        traceback.print_exc()
    
    return results

def diagnose_current_browser():
    """
    Diagnose current browser (if it's open)
    """
    
    print("[SEARCH] SEARCHING FOR ACTIVE BROWSER...")
    
    try:
        # Try to find active browser through Houdini
        import hou
        
        # Search for browser panels
        desktop = hou.ui.curDesktop()
        pane_tabs = desktop.paneTabsOfType(hou.paneTabType.PythonPanel)
        
        ftrack_panels = []
        for tab in pane_tabs:
            if 'ftrack' in tab.name().lower() or 'browser' in tab.name().lower():
                ftrack_panels.append(tab)
        
        if ftrack_panels:
            print(f"[OK] Found {len(ftrack_panels)} ftrack panels")
            
            # Try to get access to API client
            for panel in ftrack_panels:
                try:
                    interface = panel.activeInterface()
                    if hasattr(interface, 'api_client'):
                        print("[OK] Found API client in panel")
                        return quick_performance_check(api_client=interface.api_client)
                    elif hasattr(interface, 'session'):
                        print("[OK] Found session in panel")
                        return quick_performance_check(session=interface.session)
                except:
                    continue
        
        print("[FAIL] Active browser not found")
        
    except ImportError:
        print("[FAIL] Houdini not available")
    except Exception as e:
        print(f"[FAIL] Browser search error: {e}")
    
    return None

def restore_cache_performance(session):
    """
    Attempt to restore cache performance
    """
    
    print("\n🔧 RESTORING CACHE PERFORMANCE")
    print("=" * 45)
    
    if not session:
        print("[FAIL] Session not available")
        return False
    
    try:
        # Clear cache
        print("🧹 Clearing cache...")
        session.cache.clear()
        print("[OK] Cache cleared")
        
        # Check result
        print("🧪 Checking result...")
        result = quick_performance_check(session=session)
        
        if result and result.get('performance_rating') in ['excellent', 'good']:
            print("🎉 Performance restored!")
            return True
        else:
            print("[WARN]  Performance is still low")
            return False
            
    except Exception as e:
        print(f"[FAIL] Restoration error: {e}")
        return False

if __name__ == "__main__":
    # For running from Houdini
    diagnose_current_browser() 