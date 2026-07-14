#_____________________ROAD MAP_____________________

"""
All necessary, callable functions
"""

#_____________________IMPORTS_____________________
import re
import os
import json
import datetime
import maya.cmds as cmds
from maya.api import OpenMaya

# In Studio
# studio_import used to replace any studio import
import studio_import
# Shotgrid
from studio_shotgrid.sg_actions import get_user
from dotenv import load_dotenv

# Relatives
from .manage_std import (import_std,
                         match_modification,
                         delete_std,
                         ConfoUpdateShotgrid)


#_____________________GLOBALS_____________________

sg_instance = studio_shotgrid.get_server()
sg_database = studio_shotgrid.get_server().sg_con.connection
SEQUENCE_NAME_PATTERN = "{episode}_{sequence}"
SHOT_FULL_NAME_SG_PATTERN = "{episode}_{shot}"
LOGGER = studio_import.get_logger("batch_snap_anim")
SHOTS_FAB_PATH = "/mnt/Projets/PROJECT/Shots"

#_____________________UTILS_____________________

def get_shot_list(episode_code):
    """
    Get all sequences and shots of a given episode
    :param episode_code: string() : Episode code for Shotgrid
    :return: episode_shots : dictionary() : dictionary containing all sequences and their shots of a given episode
    """
    episode_info = sg_database.find(
        "Episode",
        [
            ["project", "name_is", "PROJECT_NAME"],
            ["code", "is", episode_code],
        ],
        ['sequences']
    )[0]
    episode_shots = dict()
    for sequence in episode_info["sequences"]:
        sequence_name = sequence["name"]
        episode_shots[sequence_name]=list()
        shots_info = sg_database.find(
        'Shot',
        [
            ['project', 'name_is', "PROJECT_NAME"],
            ['sg_sequence', 'name_is', sequence_name],
            ['sg_status_list', 'is_not', 'omt']
        ],
        ['code']
        )
        for shot in shots_info:
            shot_name = shot["code"]
            episode_shots[sequence_name].append(shot_name)

    return episode_shots


def get_episode_list():
    """
    Get episodes list from folder in SHOTS_FAB_PATH
    :param SHOTS_FAB_PATH; string() : Path to episode list in fab
    :return: episode_lst: list() :
    """
    episode_lst = list()
    if not os.path.exists(SHOTS_FAB_PATH):
        LOGGER.error("Shots Fab path does not exist")
    else:
        lst = os.listdir(SHOTS_FAB_PATH)
        lst.sort()
        for folder in lst:
            if folder.startswith("ep"):
                episode_number = folder.replace("ep", "")
                episode_lst.append(episode_number)
    return episode_lst


def create_batch_shot_list(sequences_lst,shots_lst):
    """
    Create a shot's list (format ep###_sq####_sh####) from selection
    :param sequences_lst: list() : selected sequences
    :param shots_lst: list() : selected shots
    :return batch_shot_lst: list() : list containing selected shots name
    """
    batch_shot_lst = list()
    for shot in shots_lst:
        shot_info = sg_database.find_one(
            'Shot',
            [
                ['project', 'name_is', "PROJECT_NAME"],
                ['code', 'is', shot],
            ],
            ['sg_sequence']
        )
        shot_full_name = shot_info["sg_sequence"]["name"] + "_" + shot.split("_")[-1]
        if shot_full_name not in batch_shot_lst:
            batch_shot_lst.append(shot_full_name)
    for sequence in sequences_lst:
        sg_shots = sg_database.find(
            "Shot",
            [
                ["project", "is", "PROJECT_NAME"],
                ["sg_sequence", "name_is", sequence],
            ],
            fields=["code"],
        )
        shots_from_seq = [x["code"].split("_")[-1] for x in sg_shots]
        for shot in shots_from_seq:
            shot_full_name = sequence + "_" + shot
            if shot_full_name not in batch_shot_lst:
                batch_shot_lst.append(shot_full_name)
    return batch_shot_lst


def replace(ctn_transform, mdu_info):
    """
    Replace a ctn with the corresponding reference and update the casting (ctn_replace tool)
    :param ctn_transform: string() : selected ctn transform node name
    :param mdu_info: dictionary() : dictionary with all the selected ctn info
    """
    ctn_connection = studio_import.get_ctn_connection(ctn_transform)
    if ctn_connection:
        reference = studio_import.get_reference_from_ctn_connection(ctn_connection)
        raise Exception(
            f"The CTN {ctn_transform!r} is already connected to the reference {reference!r}"
        )

    prop_name = mdu_info["name"]

    # list existing references
    reference_node_pattern = studio_import.ASSET_REF_NODE_PATTERN.format(
        type=studio_import.PRP_TYPE, name=prop_name, index="(?P<index>\d{3})"
    )

    indices = list()
    references = list()
    for reference in cmds.ls(type="reference"):
        match = re.fullmatch(reference_node_pattern, reference)
        if not match:
            continue

        index = int(match.groupdict()["index"])
        indices.append(index)

        references.append(reference)

    last_index = max(indices) if indices else 0
    next_index = last_index + 1
    asset_count = len(indices)

    reference = None

    # reference / namespace
    flush_undo_needed = False
    if reference:
        namespace = cmds.referenceQuery(reference, namespace=True)[1:]
    else:
        namespace = studio_import.ASSET_NAMESPACE_PATTERN.format(
            type=studio_import.PRP_TYPE, name=prop_name, index=f"{next_index:03}"
        )
        reference = f"{namespace}RN"

        # import ref and upd sg
        studio_import.import_asset(prop_name, namespace)

        new_asset_count = asset_count + 1
        studio_import.add_asset_to_current_sg_casting(prop_name, new_asset_count)

        flush_undo_needed = True

    # connection grp
    ctn_connections_grp = "CTN_CONNECTIONS"

    if not cmds.objExists(ctn_connections_grp):
        ctn_connections_grp = cmds.group(empty=True, name=ctn_connections_grp)

        if cmds.objExists(studio_import.LAY_GRP):
            cmds.parent(ctn_connections_grp, studio_import.LAY_GRP)

    # ctn connection
    connection_name = studio_import.CONNECTION_NAME_PATTERN.format(
        name=namespace.replace(f"{studio_import.PRP_TYPE}_", "")
    )
    studio_import.create_ctn_connection_group(
        ctn_transform, reference, name=connection_name, parent=ctn_connections_grp
    )

    # snap
    ctn_translation = cmds.xform(
        ctn_transform, translation=True, worldSpace=True, q=True
    )
    ctn_rotation = cmds.xform(ctn_transform, rotation=True, worldSpace=True, q=True)
    ctn_scale = cmds.xform(ctn_transform, scale=True, worldSpace=False, q=True)

    main_ctrl = studio_import.MAIN_CTRL_PATTERN.format(namespace=namespace)
    cmds.xform(main_ctrl, translation=ctn_translation, worldSpace=True)
    cmds.xform(main_ctrl, rotation=ctn_rotation, worldSpace=True)
    cmds.xform(main_ctrl, scale=ctn_scale, worldSpace=False)

    # hide ctn
    cmds.hide(ctn_transform)

    # select main ctrl
    cmds.select(main_ctrl)

    # flush undo if ref imported to avoid unexpected result on undo
    if flush_undo_needed:
        cmds.flushUndo()


def get_user_entity(user_id):
    """
    Get current shotgrid user id
    :param user_id: string(): shotgrid user id
    :return: user_id: string()
    """
    sg = studio_import.get_sg()
    return sg.find_one(
        "HumanUser",
        filters=[["id", "is", user_id]],
        fields=["sg_name_ad", "groups"],
    )


def check_assignation(task_name):
    """
    Check shotgrid assignation on selected task. If not, assign current user
    :param task_name: string(): task name (from UI)
    """
    sg = studio_import.get_sg()
    # scene info
    section, key, scene_info = studio_import.get_current_scene_path_info()

    if not scene_info:
        raise Exception("Current scene path is not valid")

    # entities
    episode_name = scene_info["episode"]
    if section == "SEQUENCES":
        sequence_name = scene_info["sequence"]
        sequence_full_name = SEQUENCE_NAME_PATTERN.format(
            episode=episode_name, sequence=sequence_name
        )

        sequence = studio_import.get_sequence_from_name(sg, sequence_full_name)
        shots = studio_import.get_shots_from_sequence_name(sg, sequence_full_name)

        entities = shots + [sequence]

    elif section == "SHOTS":
        shot_name = scene_info["shot"]
        shot_full_name = SHOT_FULL_NAME_SG_PATTERN.format(
            episode=episode_name, shot=shot_name
        )

        shots = studio_import.get_shots_from_shot_name(sg, shot_full_name)

        entities = shots

    else:
        raise Exception(f"Unexpected section {section!r}.")

    # tasks
    tasks = studio_import.get_tasks_from_entities(
        sg, task_name, entities, ["task_assignees", "entity"]
    )

    # entities without assignees
    entities_without_assignees = list()
    for task in tasks:
        assignee = task.get("task_assignees")
        entity = task.get("entity", dict())
        entity_name = entity.get("name", "unknown")

        if not assignee:
            user_entity = get_user_entity(get_user().infos["id"])
            task_id = task.get("id")
            sg.update("Task", task_id, {"task_assignees": [user_entity]})


def get_current_batch(day_batch_path):
    """

    :param day_batch_path:
    :return:
    """
    pattern = re.compile(r"^Batch_(\d{3})$")
    batch_numbers = []
    for item in day_batch_path.iterdir():
        match = pattern.match(item.name)
        if match:
            batch_num = int(match.group(1))
            batch_numbers.append(batch_num)
    next_number = max(batch_numbers, default=0) + 1
    new_log_name = f"Batch_{next_number:03d}"
    log_path = day_batch_path / new_log_name

    return log_path, new_log_name


def get_roller_order():
    """
    Get roller order according to the roller existing in the scene
    # TODO : Adapt to create the dictionary from scratch, querying the relation from matrix constraint or position proximity
    :return: roller_dict: dictionary(): dictionary corresponding to the current roller
    """
    roller_dict = dict()
    set_list = cmds.listRelatives("SET", children=True, type="transform")
    if any(["RollerStreetSTDA" in element for element in set_list]):
        roller_dict = studio_import.roller_dict_street
    elif any(["RollerJungleSTDA" in element for element in set_list]):
        roller_dict = studio_import.roller_dict_jungle
    return roller_dict


def create_matrix_constraint(
        parent, child, maintain_offset=True, name="matrix_constraint", force=False
):
    """
    Create a matrix constraint between two objects on rotate and translate
    :param parent: string() : parent object
    :param child: string() : child object
    :param maintain_offset: boolean(): whether to keep current offset or not
    :param name: string(): name to use for the nodes
    :param force: boolean(): whether to force the connections or not
    """
    mult = cmds.createNode("multMatrix", name=f"{name}_mult")

    if maintain_offset:
        parent_world_matrix = cmds.getAttr(f"{parent}.worldMatrix[0]")
        parent_world_matrix = OpenMaya.MMatrix(parent_world_matrix)

        child_world_matrix = cmds.getAttr(f"{child}.worldMatrix[0]")
        child_world_matrix = OpenMaya.MMatrix(child_world_matrix)

        offset_matrix = child_world_matrix * parent_world_matrix.inverse()

        cmds.setAttr(f"{mult}.matrixIn[0]", list(offset_matrix), type="matrix")

    cmds.connectAttr(f"{parent}.worldMatrix[0]", f"{mult}.matrixIn[1]")
    cmds.connectAttr(f"{child}.parentInverseMatrix[0]", f"{mult}.matrixIn[2]")

    decompose_matrix = cmds.createNode("decomposeMatrix", name=f"{name}_decompose")
    cmds.connectAttr(f"{mult}.matrixSum", f"{decompose_matrix}.inputMatrix")

    for attr in ("translate", "rotate", "scale", "shear"):
        decompose_plug = f"{decompose_matrix}.output{attr.title()}"
        child_plug = f"{child}.{attr}"
        cmds.connectAttr(decompose_plug, child_plug, force=force)


def update_roller_vup():
    """
    Update the roller process after set dress update
    """
    roller_dict = get_roller_order()
    for locator, children in roller_dict.items():
        for child in children:
            create_matrix_constraint(locator, child)


def remove_referenced(nodes):
    """
    Iterate through a list of node and remove any referenced one
    :param nodes: List of nodes
    :return: List of not referenced nodes
    """
    node_not_referenced = list()
    for node in nodes:
        if cmds.referenceQuery(node, isNodeReferenced=True):
            continue
        node_not_referenced.append(node)
    return node_not_referenced


def get_std_info(entity, version="last"):
    """
    Get published version of a set-dress
    :param entity: string : wanted set-dress selected in the UI
    :param version: string : wanted version of the STD (Default : "last")
    :return: json_path : string : filepath to the correct json file
    :return: atom_path : string : filepath to the correct atom file
    :return: base_context : dict : dictionary containing the STD infos
    """
    base_context = {
        "project_name": "PROJECT",
        "trigram": "PRJT",
        "type": "STD",
        "entity": f"{entity}",
        "step": "STG",
        "task": "staging",
        "ext": "json",
        "labels": [],
    }
    pub_dir_path = studio_import.make(
        "SETDRESSES", "publish_base_path", base_context
    )
    if os.path.exists(pub_dir_path):
        pub_dir = sorted([x.path for x in os.scandir(pub_dir_path) if x.is_dir()])
        if version == "last":
            base_context["version"] = pub_dir[-1].split("/")[-1][-3:]
        else:
            base_context["version"] = f"{version}"
            json_path = studio_import.make(
                "SETDRESSES", "publish_path", base_context
            )
            if not os.path.exists(json_path):
                LOGGER.warning(
                    f"Could not find {entity} {version}, opening last available version"
                )
                base_context["version"] = pub_dir[-1].split("/")[-1][-3:]
        json_path = studio_import.make("SETDRESSES", "publish_path", base_context)
        base_context["ext"] = "atom"
        atom_path = studio_import.make("SETDRESSES", "publish_path", base_context)
        if os.path.exists(json_path):
            LOGGER.info(f"Creating STD using {json_path}")
            return json_path, atom_path, base_context
        else:
            LOGGER.error(f"Could not find {json_path}")
            return


def list_repath_error():
    """
    List all repath error for node
    :return: error_path: list(string()): list paths returning error
    :return: error_nodes:  list(string()): list nodes with any repath error
    """
    path_list = list()
    node_list = list()
    error_nodes = list()
    error_path = list()
    for cache_node in cmds.ls(type="gpuCache"):
        path = cmds.getAttr(f"{cache_node}.cacheFileName")
        path_list.append(path)
        node_list.append(cache_node)
    for proxy_node in cmds.ls(type="RedshiftProxyMesh"):
        path = cmds.getAttr(f"{proxy_node}.fileName")
        path_list.append(path)
        node_list.append(proxy_node)
    for reference_node in cmds.ls(rf=True):
        path = cmds.referenceQuery(reference_node, filename=True)
        path_list.append(path)
        node_list.append(reference_node)
    for each_path in path_list:
        if ".ma{" in each_path:
            path = each_path.split("{")[0]
        else:
            path = each_path
        if not os.path.exists(path):
            error_path.append(path)
            error_nodes.append(node_list[path_list.index(each_path)])
        else:
            continue
    return error_path, error_nodes


def task_to_step(task):
    """
    Get step name from selected task
    :param task: string(): task name from UI
    :return: step: string(): step corresponding to selected task
    """
    sg_instance = studio_import.get_server()
    if task in ["common", "posevariant"]:
        return "COM"
    if task == "assetbase":
        return "ASB"
    step = sg_instance.sg_con.find_one(
        "Task",
        [["content", "is", task]],
        fields=["id", "step", "step.Step.short_name", "content", "entity"],
    ).get("step.Step.short_name")
    return step


def repath_to_fab(path, type):
    """
    Repath node path from to studio path
    :param path: string(): current path (raising an error)
    :param type: string(): node type
    :return: studio_path: string(): fixed path
    """
    file_path = cmds.file(query=True, sceneName=True)
    file = os.path.basename(file_path)
    entry = {
        "name": f"{file}",
        "work_maya_file_path": f"{file_path}",
        "context": {
            "project_name": "PROJECT",
            "trigram": "PRJT",
        },
    }
    pm_context = {
        "project_name": entry["context"]["project_name"],
        "trigram": entry["context"]["trigram"],
    }
    asset_labels_regex = "(?P<Path>.+)/(?P<Filename>(?P<Project>[a-zA-Z]+)_(?P<AssetType>[A-Z0-9]+)_(?P<AssetName>[a-zA-Z]+)_(?P<AssetTask>[a-zA-Z]+)(?P<Version>_v[0-9]{3})?(?P<Labels>(--[a-zA-Z]+)*)?).(?P<Extension>.+)"
    asset_path_pattern = "(?P<Path>.+)/(?P<Filename>(?P<Project>[a-zA-Z]+)_(?P<AssetType>[a-zA-Z0-9]+)_(?P<AssetName>[a-zA-Z]+)_(?P<AssetTask>[a-zA-Z]+)(?P<Extra>_[a-zA-Z]+)?_v(?P<Version>[0-9]{3})).(?P<Extension>.+)"
    # Relinking GPU Cache nodes
    if type == "gpuCache":
        if "posevariant" in path:
            pattern = re.compile(asset_labels_regex)
            match = pattern.match(path)
            if not match:
                return path
            pm_context.update(
                {
                    "trigram": match.group("Project"),
                    "step": task_to_step(match.group("AssetTask")),
                    "type": match.group("AssetType"),
                    "entity": match.group("AssetName"),
                    "com_task": match.group("AssetTask"),
                    "task": match.group("AssetTask"),
                    "ext": match.group("Extension"),
                    "version": (
                        match.group("Version").replace("_v", "")
                        if match.group("Version")
                        else None
                    ),
                    "labels": (
                        match.group("Labels").split("--")[1:]
                        if match.group("Labels")
                        else []
                    ),
                }
            )
            studio_path = (
                studio_import.make("ASSETS", "com_unversioned_file_path", pm_context)
                .replace("20_RND", "50_FAB")
                .replace("RND", "FAB")
            )
            if not os.path.exists(studio_path):
                if "gpu" in pm_context["labels"]:
                    studio_path = studio_path.replace("--gpu", "", 1)
        else:
            pattern = re.compile(asset_path_pattern)
            match = pattern.match(path)
            if not match:
                return path
            pm_context.update(
                {
                    "type": match.group("AssetType"),
                    "entity": match.group("AssetName"),
                    "step": task_to_step(match.group("AssetTask")),
                    "task": match.group("AssetTask"),
                    "version": match.group("Version"),
                    "software": "MAYA",
                    "ext": "abc",
                    "labels": [],
                }
            )
            studio_path = (
                studio_import.make("ASSETS", "publish_path", pm_context)
                .replace("20_RND", "50_FAB")
                .replace("RND", "FAB")
            )

        return studio_path

    # Relinking Proxy nodes
    if type == "RedshiftProxyMesh":
        if "posevariant" in path:
            pattern = re.compile(asset_labels_regex)
            match = pattern.match(path)
            if not match:
                return path
            pm_context.update(
                {
                    "trigram": match.group("Project"),
                    "step": task_to_step(match.group("AssetTask")),
                    "type": match.group("AssetType"),
                    "entity": match.group("AssetName"),
                    "com_task": match.group("AssetTask"),
                    "task": match.group("AssetTask"),
                    "ext": match.group("Extension"),
                    "version": match.group("Version").replace("_v", "")
                    if match.group("Version")
                    else None,
                    "labels": match.group("Labels").split("--")[1:]
                    if match.group("Labels")
                    else [],
                }
            )
            studio_path = (
                studio_import.make("ASSETS", "com_unversioned_file_path", pm_context)
                .replace("20_RND", "50_FAB")
                .replace("RND", "FAB")
            )
        else:
            pattern = re.compile(asset_path_pattern)
            match = pattern.match(path)
            if not match:
                return path
            pm_context.update(
                {
                    "type": match.group("AssetType"),
                    "entity": match.group("AssetName"),
                    "step": task_to_step(match.group("AssetTask")),
                    "task": match.group("AssetTask"),
                    "version": match.group("Version"),
                    "software": "MAYA",
                    "ext": "rs",
                    "labels": [],
                }
            )
            studio_path = (
                studio_import.make("ASSETS", "publish_path", pm_context)
                .replace("20_RND", "50_FAB")
                .replace("RND", "FAB")
            )

        return studio_path


def fix_repath():
    """
    Fix detected repath error
    # TODO: The process is currently targeting and fixing only previously detected repath error. It would need to be more open
    :return: error_path: list(string()): list of path still returning error
    :return: error_nodes:  list(string()): list of nodes still returning any repath error
    """
    errors_node = list()
    errors_path = list()
    # Relinking GPU Cache nodes
    for cache_node in cmds.ls(type="gpuCache"):
        path = cmds.getAttr(f"{cache_node}.cacheFileName")
        if not os.path.exists(path):
            if " " in path:
                path = path.replace(" ", "")
            if "EXTERNAL_FILES" in path:
                path = repath_to_fab(path, type="gpuCache")
            if "ShuytersClosed" in path:
                path = path.replace("ShuytersClosed", "GreenClosed")
            if "--gpu/PRJT_" in path:
                path = path.replace("--gpu/PRJT_", "", 1)
            if os.path.exists(path):
                cmds.setAttr(f"{cache_node}.cacheFileName", path, typ="string")
            else:
                errors_node.append(cache_node)
                errors_path.append(path)
        else:
            continue
    # Relinking Proxy nodes
    for proxy_node in cmds.ls(type="RedshiftProxyMesh"):
        path = cmds.getAttr(f"{proxy_node}.fileName")
        if not os.path.exists(path):
            if " " in path:
                path = path.replace(" ", "")
            if "$EXTERNAL_FILES" in path:
                path = repath_to_fab(path, type="RedshiftProxyMesh")
            if "ShuytersClosed" in path:
                path = path.replace("ShuytersClosed", "GreenClosed")
            if "--gpu/PRJT_" in path:
                path = path.replace("--gpu/PRJT_", "", 1)
            if ".ma{" in path:
                path = path.split("{")[0]
            if os.path.exists(path):
                cmds.setAttr(f"{proxy_node}.fileName", path, typ="string")
            else:
                errors_node.append(proxy_node)
                errors_path.append(path)
        else:
            continue
    return errors_node, errors_path


def change_set_dress(wanted_setdress, old_setdress, offset_needed=False):
    """
    Change the current set-dress to any wanted set-dress
    # TODO: The script is currently only working for set-dress in the "same space".
            It could work with animation offset (toolbox confo) but it's a process that should not be batched directly into snap due to many variable and possible errors (need for visual check).
    :param wanted_setdress: string(): wanted set-dress name
    :param old_setdress: string(): current set-dress name
    :param offset_needed: boolean(): whether or not to launch and animation and spacial offset (default False, function is not implemented in batch right now)
    """
    if not cmds.objExists("|ALL|STG|ENV"):
        cmds.createNode("transform", name="ENV")
        if not cmds.objExists("ALL"):
            cmds.createNode("transform", name="ALL")
            if not cmds.objExists("STG"):
                cmds.createNode("transform", name="STG")
                cmds.parent("STG", "ALL")
        cmds.parent("ENV", "STG")
    if not cmds.objExists("|ALL|STG|SET"):
        cmds.createNode("transform", name="SET")
        cmds.parent("SET", "STG")
    if not cmds.objExists("|ALL|STG|MDU"):
        cmds.createNode("transform", name="MDU")
        cmds.parent("SET", "MDU")

    if wanted_setdress:
        # Import new set dress
        json_dir, atom_dir, base_context = get_std_info(wanted_setdress)
        import_std(json_dir, atom_dir)

        # Edit existing config node
        if cmds.objExists("*_anim__cfg"):
            config_node = cmds.ls("*_anim__cfg")
            cmds.setAttr(f"{config_node[0]}.set_dress_info", lock=False)
            cmds.setAttr(
                f"{config_node[0]}.set_dress_info",
                json.dumps(
                    {
                        "version": base_context["version"],
                        "entity_name": base_context["entity"],
                    }
                ),
                type="string",
                lock=True,
            )
            LOGGER.info("Edited anim__config node to match new STD")

        # Create bck__cfg node
        config_node = cmds.createNode("network", name="change_std_bck__cfg")
        cmds.addAttr(config_node, longName="modification_date", dataType="string")
        current_time = datetime.datetime.now()
        cmds.setAttr(
            f"{config_node}.modification_date",
            str(current_time),
            type="string",
            lock=True,
        )
        cmds.addAttr(config_node, longName="STD_changes", dataType="string")
        std_list = [old_setdress]
        cmds.setAttr(
            f"{config_node}.STD_changes",
            json.dumps(f"Old STD : {std_list}, Current STD : ['{wanted_setdress}']"),
            type="string",
            lock=True,
        )
        LOGGER.info("Created and edited change_std_bck__cfg to keep scene changes")

        # Offset animation

        # Conform set dress
        new_std = list()
        old_std = list()
        old_set = list()
        for each_std in cmds.listRelatives("ENV", children=True):
            if wanted_setdress in each_std:
                new_std.append(each_std)
            else:
                old_std.append(each_std)
                try:
                    set_grp = each_std.replace("_ctn", ":SET")
                    set_list = cmds.listRelatives(set_grp, children=True)
                except Exception as e:
                    print(
                        f"{each_std.replace('_ctn', ':SET')} raises an error: {e}"
                    )
                else:
                    for each in set_list:
                        old_set.append(each)
        for each_std in cmds.listRelatives("SET", children=True):
            if wanted_setdress in each_std:
                new_std.append(each_std)
            else:
                old_std.append(each_std)
                try:
                    set_grp = each_std.replace("_ctn", ":SET")
                    set_list = cmds.listRelatives(set_grp, children=True)
                except Exception as e:
                    print(
                        f"{each_std.replace('_ctn', ':SET')} raises an error: {e}"
                    )
                else:
                    for each in set_list:
                        old_set.append(each)
        match_modification(new_std, old_std, old_set)

        # Delete old set dress and update shotgrid
        item = list()
        set_names = list()
        std_lst = list()

        env_lst = cmds.listRelatives("ENV", children=True)
        set_lst = cmds.listRelatives("SET", children=True)

        if env_lst:
            for each_env in env_lst:
                std_lst.append(each_env)
        if set_lst:
            for each_set in set_lst:
                std_lst.append(each_set)
        for sets in std_lst:
            if sets.startswith(f"STD_{old_setdress}_001:"):
                item.append(sets)
        if not item:
            print("rip")
        else:
            delete_std(item)

        # Update Shotgrid
        wanted_name = wanted_setdress
        if not wanted_name:
            print("You need to select a set in the 'You want to load:' list")
        else:
            entry = studio_import.get_pm_context()
            load_dotenv(os.getenv("API_KEY_ENV_PATH"))
            ConfoUpdateShotgrid(entry["project_name"], entry["env_name"], wanted_name)


def atom_export(selection, file_path):
    """
    Export an atom animation
    :param selection: list : Objects to export the animation of
    :param file_path: string : filepath to the atom file
    """
    cmds.select(clear=True)
    cmds.select(selection)
    cmds.file(
        file_path,
        force=True,
        exportSelected=True,
        options=(
            "precision=8;"
            "statics=1;"
            "baked=0;"
            "sdk=0;"
            "constraint=0;"
            "animLayers=0;"
            "selected=selectedOnly;"
            "whichRange=2;"
            "range=101:101;"
            "hierarchy=none;"
            "controlPoints=0;"
            "useChannelBox=1;"
            "options=keys;"
            "copyKeyCmd=-animation objects -time >101:101> -float >101:101> -option keys -hierarchy none -controlPoints 0 "
        ),
        type="atomExport",
    )


def atom_import(selection, file_path, search="", replace=""):
    """
    Import and apply an atom animation
    :param selection: list : Objects to import the animation on
    :param file_path: string : filepath to the atom file
    :param search: string : String to search for in the imported atom file
    :param replace: string : String to replace the searched string in the imported atom file
    """
    cmds.select(clear=True)
    cmds.select(selection)
    if search != "":
        cmds.file(
            file_path,
            force=True,
            i=True,
            options=""
                    ";"
                    ";"
                    "targetTime=3;"
                    "option=scaleReplace;"
                    "match=string;"
                    ";"
                    "selected=selectedOnly;"
                    f"search={search};"
                    f"replace={replace};"
                    "prefix=;"
                    "suffix=;"
                    f"mapFile=/home/{os.getlogin()}/maya/projects/default/data/;",
            type="atomImport",
        )
    else:
        cmds.file(
            file_path,
            force=True,
            i=True,
            options=""
                    ";"
                    ";"
                    "targetTime=3;"
                    "option=scaleReplace;"
                    "match=string;"
                    ";"
                    "selected=selectedOnly;"
                    "search=;"
                    "replace=;"
                    "prefix=;"
                    "suffix=;"
                    "mapFile=/home/user/maya/projects/default/data/;",
            type="atomImport",
        )


