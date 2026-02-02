import hou
from .logger_utils import get_logger

logger = get_logger("ftrack.node_utils")

def get_parm(node, parm_name):
    if node:
        return node.parm(parm_name)
    return None

def get_parm_value(node, parm_name, default=None):
    parm = get_parm(node, parm_name)
    if parm:
        return parm.eval()
    return default

def get_parm_evaluated_string(node, parm_name, default=""):
    value = get_parm_value(node, parm_name)
    if value is not None:
        return str(value)
    return default

def set_parm(node, parm_name, value):
    parm = get_parm(node, parm_name)
    if parm:
        try:
            parm.set(value)
        except Exception:
            pass

def set_multiple_parms(node, parm_dict):
    for k, v in parm_dict.items():
        set_parm(node, k, v)

def copy_parm_templates(source_node, target_node):
    source_group = source_node.parmTemplateGroup()
    target_group = target_node.parmTemplateGroup()
    # First copy all top-level templates
    for template in source_group.entries():
        if not target_group.find(template.name()):
            target_group.append(template)
    # Remove blacklisted parameters even if they were nested inside folders
    target_node.setParmTemplateGroup(target_group)
    try:
        ptg = target_node.parmTemplateGroup()
        if ptg.find('axissystem'):
            ptg.remove('axissystem')
            target_node.setParmTemplateGroup(ptg)
    except Exception:
        pass

def create_output_nodes(parent_node, source_node):
    node_type = source_node.type().name().lower()
    num_outputs = len(source_node.outputConnectors())
    
    for i in range(num_outputs):
        output_node = parent_node.createNode("output", f"OUT_{i}")
        output_node.setInput(0, source_node, i)
        
        if output_node.parm("outputidx"):
            output_node.parm("outputidx").set(i)
        
        color = hou.Color((0.5, 0.5, 0.5))
        if "fbxcharacterimport" in node_type:
            if i == 0: color = hou.Color((0.0, 0.68, 1.0))
            elif i == 1: color = hou.Color((0.6, 0.6, 0.6))
            elif i == 2: color = hou.Color((1.0, 0.725, 0.0))
        elif "fbxanimimport" in node_type:
            if i == 0: color = hou.Color((1.0, 0.725, 0.0))

        output_node.setColor(color)
        output_node.moveToGoodPosition()

def insert_metadata_sop(subnet_node, hda_node):
    parent_type = get_parm_evaluated_string(hda_node, 'Type')
    component_name = get_parm_evaluated_string(hda_node, 'ComponentName')
    need_pointwrangle = (parent_type.lower() == 'animation' and component_name.lower() in ['anim', 'animation'])
    
    for output_node in [n for n in subnet_node.children() if n.type().name() == 'output']:
        if not output_node.inputConnections():
            continue
            
        input_conn = output_node.inputConnections()[0]
        loader_node = input_conn.inputNode()
        output_index = get_parm_value(output_node, "outputidx", 0)
        
        last_node_in_chain = loader_node
        
        if need_pointwrangle:
            pointwrangle = subnet_node.createNode('attribwrangle', f'fix_name_{output_node.name()}')
            set_parm(pointwrangle, 'class', 2)
            set_parm(pointwrangle, 'snippet', 's@name = split(s@name,":")[-1];')
            pointwrangle.setInput(0, loader_node, output_index)
            last_node_in_chain = pointwrangle
        
        python_sop = subnet_node.createNode('python', f'meta_{output_node.name()}')
        python_sop.addSpareParmTuple(hou.StringParmTemplate('source_node', 'Source Node', 1, string_type=hou.stringParmType.NodeReference))
        set_parm(python_sop, 'source_node', python_sop.relativePathTo(hda_node))

        python_code = """
node = hou.pwd()
geometry = node.geometry()
source_path = node.parm('source_node').eval()
parent_node = hou.node(source_path)
if parent_node:
    comp_id = parent_node.parm('componentid').eval() if parent_node.parm('componentid') else ''
    metadata = parent_node.parm('metadict').eval() if parent_node.parm('metadict') else ''
    variables = parent_node.parm('variables').eval() if parent_node.parm('variables') else ''
    
    for attrib_name, attrib_value in [('ftrack_component_id', comp_id), ('ftrack_metadata', metadata), ('ftrack_variables', variables)]:
        if geometry.findGlobalAttrib(attrib_name) is None:
            if isinstance(attrib_value, dict):
                geometry.addAttrib(hou.attribType.Global, attrib_name, {})
            else:
                geometry.addAttrib(hou.attribType.Global, attrib_name, '')
        geometry.setGlobalAttribValue(attrib_name, attrib_value)
"""
        set_parm(python_sop, 'python', python_code)
        
        if last_node_in_chain == loader_node:
            python_sop.setInput(0, loader_node, output_index)
        else:
            python_sop.setInput(0, last_node_in_chain)
        output_node.setInput(0, python_sop)
        
        python_sop.moveToGoodPosition()
        if 'pointwrangle' in locals() and last_node_in_chain == pointwrangle:
            pointwrangle.setPosition(python_sop.position() + hou.Vector2(-2, 0))
            
    subnet_node.layoutChildren()

def link_hda_to_subnet(hda_node, subnet_node):
    """Links the HDA's file_path to the subnet's fbxfile parameter."""
    hda_file_parm = get_parm(hda_node, "file_path")
    subnet_fbx_parm = get_parm(subnet_node, "fbxfile")
    if hda_file_parm and subnet_fbx_parm:
        expression = f'`chs("{hda_file_parm.path()}")`'
        logger.info(f"Linking {subnet_fbx_parm.path()} to {hda_file_parm.path()} with expression: {expression}")
        set_parm(subnet_node, "fbxfile", expression)
    else:
        logger.warning(f"Could not link HDA to Subnet. Parm missing.")

def delete_time_channel(subnet_node):
    """
    Deletes expression and keyframes from the 'time' parameter on the subnet node
    by explicitly clearing the expression and deleting all keyframes.
    """
    time_parm = subnet_node.parm("time")
    if time_parm:
        logger.info(f"Attempting to clear 'time' on {subnet_node.path()}")
        try:
            if time_parm.expression():
                time_parm.setExpression("")
                logger.info(f"Cleared expression from 'time' on {subnet_node.path()}")

            time_parm.deleteAllKeyframes()
            logger.info(f"Cleared keyframes from 'time' on {subnet_node.path()}")
            
            # Set to a default static value
            time_parm.set(0)

        except Exception as e:
            logger.error(f"Failed to clear 'time' channel on {subnet_node.name()}: {e}")
    else:
        logger.warning(f"'time' parameter not found on {subnet_node.path()}")

def apply_post_processing(subnet_node, template):
    """
    Applies a series of post-processing functions based on the template config.
    """
    post_process_steps = template.get("post_process", [])
    
    function_map = {
        "delete_time_channel": delete_time_channel
    }
    
    for step_name in post_process_steps:
        func = function_map.get(step_name)
        if func:
            logger.info(f"Applying post-processing step: {step_name}")
            func(subnet_node)
        else:
            logger.warning(f"Post-processing function '{step_name}' not found.")

def link_subnet_to_loader(subnet_node, loader_node):
    """Links all matching parameters from the loader node back to the parent subnet."""
    for parm in loader_node.parms():
        parm_name = parm.name()
        if parm_name.lower() == 'axissystem':
            continue
        if subnet_node.parm(parm_name):
            try:
                expression = f'ch("../{parm_name}")'
                if parm.parmTemplate().type() == hou.parmTemplateType.String:
                    expression = f'chs("../{parm_name}")'
                parm.setExpression(expression)
            except hou.PermissionError:
                pass 
            except Exception as e:
                logger.warning(f"Could not link parameter '{parm_name}': {e}")

def find_empty_position_near_node(reference_node, exclude_nodes=None, search_radius=3.0):
    """
    Finds an empty position near the reference node by checking multiple directions.
    Returns the best available position.
    """
    if exclude_nodes is None:
        exclude_nodes = []
    
    ref_pos = reference_node.position()
    parent_context = reference_node.parent()
    
    # Define search directions in order of preference: below, right, left, above
    search_directions = [
        hou.Vector2(0, -2),    # Below (preferred for outputs)
        hou.Vector2(3, 0),     # Right
        hou.Vector2(-3, 0),    # Left  
        hou.Vector2(0, 2),     # Above
        hou.Vector2(3, -2),    # Bottom-right
        hou.Vector2(-3, -2),   # Bottom-left
        hou.Vector2(6, 0),     # Far right
        hou.Vector2(-6, 0),    # Far left
    ]
    
    for direction in search_directions:
        candidate_pos = ref_pos + direction
        
        # Check if this position conflicts with existing nodes
        has_conflict = False
        for node in parent_context.children():
            if node == reference_node or node in exclude_nodes:
                continue
                
            node_pos = node.position()
            distance = (node_pos - candidate_pos).length()
            
            # If another node is too close, this position is not good
            if distance < 1.8:  # Minimum distance between nodes
                has_conflict = True
                break
        
        # If no conflict, this is our position
        if not has_conflict:
            logger.info(f"Found empty position at {candidate_pos} (direction: {direction})")
            return candidate_pos
    
    # If all preferred positions are taken, use a fallback
    fallback_pos = ref_pos + hou.Vector2(0, -4)  # Far below
    logger.info(f"Using fallback position at {fallback_pos}")
    return fallback_pos

def position_subnet_smartly(subnet, hda_node):
    """
    Positions the subnet in a good location relative to the HDA node.
    Uses intelligent positioning to avoid conflicts with existing nodes.
    """
    try:
        # Find the best empty position near the HDA
        best_position = find_empty_position_near_node(hda_node, exclude_nodes=[subnet])
        
        # Set the calculated position
        subnet.setPosition(best_position)
        logger.info(f"Smart positioned subnet at {best_position} relative to HDA at {hda_node.position()}")
        
    except Exception as e:
        logger.warning(f"Smart positioning failed, using default: {e}")
        subnet.moveToGoodPosition()

def create_loader_subnet(hda_node, template):
    creation_context = hda_node.parent()
    subnet_name = f"loader_{template['name']}_{hda_node.name()}"
    
    existing_subnet = creation_context.node(subnet_name)
    if existing_subnet:
        existing_subnet.destroy()

    subnet = creation_context.createNode("subnet", subnet_name)
    
    # Use smart positioning instead of default moveToGoodPosition
    position_subnet_smartly(subnet, hda_node)

    # Hide default subnet parameters before adding new ones
    hide_all_parameters(subnet)

    # Set shape and connect to parent HDA
    subnet.setUserData("nodeshape", "circle")
    subnet.setInput(0, hda_node)

    # Create the actual loader node inside the subnet
    loader_node = subnet.createNode(template["node_type"], template["name"])
    loader_node.moveToGoodPosition()

    copy_parm_templates(loader_node, subnet)
    # Ensure subnet defaults before linking back to loader
    try:
        rn = subnet.parm('removenamespaces')
        if rn:
            rn.set(1)
    except Exception:
        pass
    link_hda_to_subnet(hda_node, subnet)
    link_subnet_to_loader(subnet, loader_node)
    apply_post_processing(subnet, template)

    create_output_nodes(subnet, loader_node)
    insert_metadata_sop(subnet, hda_node)
    
    subnet.layoutChildren()
    
    # Select and frame the newly created subnet for better UX
    try:
        subnet.setSelected(True, clear_all_selected=True)
        logger.info(f"Selected newly created subnet: {subnet.path()}")
        
        # Try to frame the subnet in the network editor
        network_editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if network_editor and network_editor.pwd() == subnet.parent():
            network_editor.frameSelection()
            logger.info("Framed newly created subnet in network editor")
    except Exception as e:
        logger.warning(f"Could not select/frame subnet: {e}")
    
    return subnet

def _collect_all_parms_recursive(ptg, all_parms):
    """
    Recursively collects all ParmTemplate objects from a ParmTemplateGroup or list.
    """
    for parm_template in ptg:
        # If it's a folder, recurse into its templates
        if parm_template.type() == hou.parmTemplateType.Folder:
            _collect_all_parms_recursive(parm_template.parmTemplates(), all_parms)
        else:
            all_parms.append(parm_template)

def hide_all_parameters(node):
    """
    Hides all parameters on a given node, including those nested in folders,
    by recursively collecting them and then hiding them on the top-level group.
    """
    if not node:
        logger.warning("hide_all_parameters called with an invalid node.")
        return
        
    logger.info(f"Attempting to hide all parameters on {node.path()}")
    try:
        ptg = node.parmTemplateGroup()
        
        # 1. Collect all parameter templates recursively
        all_parms_list = []
        _collect_all_parms_recursive(ptg.entries(), all_parms_list)

        # 2. Hide each collected template using the main group
        for parm_template in all_parms_list:
            # Check if the template is already hidden to avoid unnecessary work
            if not parm_template.isHidden():
                ptg.hide(parm_template, True)
            
        # 3. Apply the modified group back to the node
        node.setParmTemplateGroup(ptg)
        logger.info(f"Successfully processed {len(all_parms_list)} parameters for hiding on {node.path()}.")
        
    except Exception as e:
        logger.error(f"Failed to hide parameters on {node.path()}: {e}", exc_info=True)
