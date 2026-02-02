import hou
import yaml
import os
import re
import fnmatch
from .logger_utils import get_logger

logger = get_logger("ftrack.template_utils")

class TemplateManager:
    """Manages loading and finding templates from YAML files."""
    def __init__(self, template_path=None):
        if template_path is None:
            base_dir = os.path.dirname(__file__)
            candidates = []
            env_file = os.environ.get('FTRACK_TEMPLATES_FILE')
            if env_file:
                candidates.append(env_file)
            env_dir = os.environ.get('FTRACK_TEMPLATES_DIR')
            if env_dir:
                candidates.append(os.path.join(env_dir, 'templates.yaml'))
            try:
                hp = os.environ.get('HOUDINI_PATH', '')
                for raw in hp.split(os.pathsep):
                    p = raw.strip().strip('&')
                    if not p:
                        continue
                    shared = os.path.join(p, 'scripts', 'python', 'ftrack_inout', 'ftrack_hou_utils', 'templates', 'templates.yaml')
                    candidates.append(shared)
            except Exception:
                pass
            candidates.append(os.path.join(base_dir, 'templates', 'templates.yaml'))
            chosen = next((c for c in candidates if c and os.path.isfile(c)), None)
            template_path = chosen or candidates[-1]
            if not chosen:
                logger.warning("No explicit templates.yaml found in overrides; falling back to local versioned file")
        
        self.templates = []
        try:
            with open(template_path, 'r') as f:
                config = yaml.safe_load(f) or {}
                self.templates = config.get('templates', [])
            logger.info(f"Successfully loaded {len(self.templates)} templates from {template_path}")
            try:
                print(f"[TPL-3.11] templates loaded: {len(self.templates)} from {template_path}")
            except Exception:
                pass
        except FileNotFoundError:
            logger.error(f"Template file not found at: {template_path}")
        except Exception as e:
            logger.error(f"Failed to load or parse templates.yaml: {e}", exc_info=True)

    def find_matching_template(self, asset_type, component_name, file_format):
        """Finds the first template that matches the given criteria.
        Rules:
          - file_format in rule is REQUIRED and must equal input (case-insensitive)
          - asset_type in rule is OPTIONAL (wildcard when omitted)
          - component_name supports: exact, glob (*, ?), prefix, suffix, regex
        """
        asset_type_l = (asset_type or "").lower()
        component_name_l = (component_name or "").lower()
        file_format_l = (file_format or "").lower()

        for template_config in self.templates:
            match_rules = template_config.get("match", {})

            rule_asset = (match_rules.get("asset_type") or "").lower()
            rule_format = (match_rules.get("file_format") or "").lower()
            if rule_asset and rule_asset != asset_type_l:
                continue
            # file_format is mandatory in rule
            if not rule_format or rule_format != file_format_l:
                continue

            exact = match_rules.get("component_name")
            prefix = match_rules.get("component_name_prefix")
            suffix = match_rules.get("component_name_suffix")
            regex = match_rules.get("component_name_regex")

            matched = False
            if isinstance(exact, str):
                exact_l = exact.lower()
                if '*' in exact_l or '?' in exact_l:
                    if fnmatch.fnmatch(component_name_l, exact_l):
                        matched = True
                elif exact_l == component_name_l:
                    matched = True
            elif isinstance(prefix, str) and component_name_l.startswith(prefix.lower()):
                matched = True
            elif isinstance(suffix, str) and component_name_l.endswith(suffix.lower()):
                matched = True
            elif isinstance(regex, str):
                try:
                    if re.match(regex, component_name or "", flags=re.IGNORECASE):
                        matched = True
                except re.error:
                    logger.warning(f"Invalid component_name_regex in template '{template_config.get('name')}': {regex}")

            if matched:
                name = template_config.get('name')
                logger.info(f"Found matching template: {name}")
                try:
                    print(f"[MATCH-3.11] {name} for {asset_type}/{component_name}/{file_format} via {__file__}")
                except Exception:
                    pass
                return template_config

        logger.warning(f"No matching template found for: {asset_type}, {component_name}, {file_format}")
        return None

# --- Post-Processing Functions ---
# These functions are designed to be called by name from the template config.
# They operate on the newly created loader node.

def delete_time_channel(node, template_config):
    """
    Finds the 'time' parameter, clears its expression if one exists,
    and then removes all its keys.
    """
    time_parm = node.parm("time")
    if time_parm:
        try:
            # First, clear any expression (like 'opstart()')
            if time_parm.expression():
                time_parm.setExpression("")
                logger.info(f"[Post-process] Cleared expression from 'time' parameter on {node.path()}")
            
            # Then, delete all keyframes
            time_parm.deleteAllKeyframes()
            
            # Finally, reset the value to 0
            time_parm.set(0) 
            logger.info(f"[Post-process] Cleared keyframes and reset 'time' parameter on {node.path()}")
        except Exception as e:
            logger.error(f"[Post-process Error] delete_time_channel: {e}")

def apply_post_processing(loader_node, template_config):
    """
    Applies a list of post-processing functions to the loader node.
    This should be called after the node is created.
    """
    post_process_list = template_config.get("post_process", [])
    if not post_process_list:
        return
        
    logger.info(f"Applying {len(post_process_list)} post-process steps to {loader_node.path()}")
    for func_name in post_process_list:
        # Assumes the function is defined in this module (template_utils.py)
        process_func = globals().get(func_name)
        if callable(process_func):
            try:
                logger.info(f"Running post-process function: '{func_name}'")
                process_func(loader_node, template_config)
            except Exception as e:
                logger.error(f"Error executing post-process function '{func_name}': {e}", exc_info=True)
        else:
            logger.warning(f"Post-process function '{func_name}' not found in template_utils.py.")


# --- Node Creation Engine (New Architecture) ---

def create_fresh_loaders_subnet(parent_node):
    """Creates a new, clean subnet next to the parent HDA."""
    subnet_name = f"{parent_node.name()}_loaders"
    parent_geo = parent_node.parent()
    old_subnet = parent_geo.node(subnet_name)
    if old_subnet:
        old_subnet.destroy()
    subnet = parent_geo.createNode("subnet", subnet_name)
    # Position it nicely relative to the HDA
    subnet.setPosition(parent_node.position() + hou.Vector2(0, -1))
    subnet.setUserData("nodeshape", "circle")
    logger.info(f"Created fresh subnet: {subnet.path()}")
    return subnet

def copy_node_interface(source_node, target_node):
    """Copies all parm templates from source_node to target_node."""
    target_ptg = target_node.parmTemplateGroup()
    for parm_template in source_node.parmTemplateGroup().parmTemplates():
        try:
            name = parm_template.name()
        except Exception:
            name = ""
        # Skip problematic parameters; we don't want axissystem on subnet
        if name and name.lower() == "axissystem":
            continue
        target_ptg.append(parm_template)
    target_node.setParmTemplateGroup(target_ptg)
    logger.info(f"Copied interface from {source_node.path()} to {target_node.path()}")
    
def link_hda_to_subnet(hda_node, subnet_node):
    """Links the HDA's file_path to the subnet's fbxfile parameter."""
    hda_parm_name = "file_path"
    # The correct parameter name on FBX import nodes is 'fbxfile'
    subnet_parm_name = "fbxfile" 
    
    hda_parm = hda_node.parm(hda_parm_name)
    subnet_parm = subnet_node.parm(subnet_parm_name)

    if hda_parm and subnet_parm:
        try:
            # Set the expression on the subnet's parameter to read from the HDA (force HScript)
            rel_path = subnet_node.relativePathTo(hda_node)
            expr = f'chs("{rel_path}/{hda_parm_name}")'
            if "axissystem" not in expr:
                subnet_parm.setExpression(expr, language=hou.exprLanguage.Hscript)
            logger.info(f"Linked HDA '{hda_parm_name}' to Subnet's '{subnet_parm_name}'.")
        except Exception as e:
            logger.error(f"Failed to link HDA parm '{hda_parm_name}' to subnet: {e}", exc_info=True)
    else:
        logger.warning(f"Could not link HDA to Subnet. Parm missing: HDA has '{hda_parm_name}'? {hda_parm is not None}. Subnet has '{subnet_parm_name}'? {subnet_parm is not None}")

def link_subnet_to_loader(subnet_node, loader_node):
    """Links the subnet's fbxfile parameter to the actual loader node inside it."""
    # The parameter name should be the same, as it was copied to the subnet.
    parm_name = "fbxfile"
    
    if subnet_node.parm(parm_name) and loader_node.parm(parm_name):
        try:
            # The loader node reads its parameter from the parent subnet (force HScript)
            expr = f'chs("../{parm_name}")'
            if "axissystem" not in expr:
                loader_node.parm(parm_name).setExpression(expr, language=hou.exprLanguage.Hscript)
            logger.info(f"Linked Subnet '{parm_name}' to Loader '{parm_name}'.")
        except Exception as e:
            logger.error(f"Failed to link Subnet parm '{parm_name}': {e}", exc_info=True)
    else:
        logger.warning(f"Could not link Subnet to Loader. Parm '{parm_name}' missing from either subnet or loader.")


def create_output_nodes_for_template(subnet_node, loader_node):
    """Creates and colors output nodes inside the subnet, with correct numbering."""
    if not loader_node or len(loader_node.outputConnectors()) == 0:
        return
    num_outputs = len(loader_node.outputConnectors())
    for i in range(num_outputs):
        # Correct Houdini numbering: starts from 0
        output_node = subnet_node.createNode("output", f"OUT_{i}")
        output_node.setInput(0, loader_node, i)
        
        # This parameter is crucial for the output node to function correctly
        if output_node.parm("outputidx"):
            output_node.parm("outputidx").set(i)
        
        # Color coding logic
        color = hou.Color((0.5, 0.5, 0.5)) # Default grey
        node_type = loader_node.type().name().lower()
        if "fbxcharacterimport" in node_type:
            if i == 0: color = hou.Color((0.0, 0.68, 1.0)) # Geometry (blue)
            elif i == 1: color = hou.Color((0.6, 0.6, 0.6)) # Capture Pose (grey)
            elif i == 2: color = hou.Color((1.0, 0.725, 0.0)) # Animation (orange)
        elif "fbxanimimport" in node_type:
            if i == 0: color = hou.Color((1.0, 0.725, 0.0)) # Animation (orange)

        output_node.setColor(color)
    logger.info(f"Created {num_outputs} colored output nodes starting from OUT_0.")


def insert_python_sop_before_outputs(subnet_node, hda_node):
    """Inserts a Python SOP with a relative link to the HDA before each geometry output."""
    for output_node in subnet_node.children():
        if output_node.type().name() == 'output' and output_node.inputConnectors():
            input_conn = output_node.inputConnections()[0]
            input_node = input_conn.inputNode()
            if input_node.type().category().name() == "Sop":
                
                python_sop = subnet_node.createNode('python', f'meta_{output_node.name()}')
                python_sop.setInput(0, input_node)
                output_node.setInput(0, python_sop, 0)
                
                # Create a spare parameter to hold the relative path to the HDA
                hda_path_parm = hou.StringParmTemplate("hda_path", "HDA Path", 1, string_type=hou.stringParmType.NodeReference)
                python_sop.addSpareParmTuple(hda_path_parm)
                python_sop.parm("hda_path").set(python_sop.relativePathTo(hda_node))
                
                # Update the python code to use the new parameter
                python_sop.parm('python').set(f"""
node = hou.pwd()
geometry = node.geometry()

# Get HDA node dynamically using the relative path parameter
hda_path = node.parm('hda_path').eval()
hda_node = node.node(hda_path)

if hda_node:
    comp_id = hda_node.parm('componentid').eval()
    metadata = hda_node.parm('metadict').eval()
    variables = hda_node.parm('variables').eval()

    geometry.addAttrib(hou.attribType.Global, 'ftrack_component_id', comp_id)
    geometry.addAttrib(hou.attribType.Global, 'ftrack_metadata', metadata)
    geometry.addAttrib(hou.attribType.Global, 'ftrack_variables', variables)
""")
                logger.info(f"Inserted Python SOP with relative HDA link on {output_node.path()}")


# --- Generator Functions ---

def create_rig_fbx_template(subnet, template_config):
    loader_node = subnet.createNode("fbxcharacterimport", "rig_loader")
    loader_node.moveToGoodPosition()
    return {"main": loader_node}

def create_anim_fbx_template(subnet, template_config):
    loader_node = subnet.createNode("fbxanimimport", "anim_loader")
    loader_node.moveToGoodPosition()
    # Sanitize parameters that can carry invalid default expressions
    try:
        axis_parm = loader_node.parm("axissystem")
        if axis_parm is not None:
            # Clear any expression first, then set default
            if axis_parm.expression():
                axis_parm.setExpression("", language=hou.exprLanguage.Hscript)
            axis_parm.set(0)
        # Clear unexpected expressions on other parms except file path link
        for parm in loader_node.parms():
            if parm.name() in ("fbxfile",):
                continue
            try:
                expr = parm.expression()
                if expr:
                    # If expression references ./axissystem, replace with evaluated value and clear
                    if 'axissystem' in expr:
                        try:
                            parm.set(parm.eval())
                        except Exception:
                            pass
                    parm.setExpression("", language=hou.exprLanguage.Hscript)
            except Exception:
                pass
        # Enforce recommended defaults
        # removenamespaces is now set only on subnet and propagated through link_subnet_to_loader that
    except Exception:
        pass
    return {"main": loader_node}


# --- Main Orchestrator ---

def create_node_from_template(template_manager, hda_node, asset_type, component_name, file_format):
    """Creates a full loader network based on the new architecture."""
    
    template_config = template_manager.find_matching_template(asset_type, component_name, file_format)
    if not template_config:
        logger.error("Failed to find a matching template.")
        return None

    subnet = create_fresh_loaders_subnet(hda_node)
    
    if template_config.get("subnet_color"):
        subnet.setColor(hou.Color(template_config["subnet_color"]))
        
    generator_func_name = template_config.get("generator")
    generator_func = globals().get(generator_func_name)
    if not generator_func:
        logger.error(f"Generator function '{generator_func_name}' not found!")
        return None
        
    nodes = generator_func(subnet, template_config)
    loader_node = nodes.get("main")

    if not loader_node:
        logger.error("Generator function did not return a 'main' node.")
        return None
    
    # Execute the plan
    copy_node_interface(loader_node, subnet)
    link_hda_to_subnet(hda_node, subnet)
    link_subnet_to_loader(subnet, loader_node)
    apply_post_processing(loader_node, template_config)
    create_output_nodes_for_template(subnet, loader_node)
    insert_python_sop_before_outputs(subnet, hda_node)

    subnet.layoutChildren()
    logger.info(f"Successfully created and configured loader network in {subnet.path()}")
    
    return subnet 