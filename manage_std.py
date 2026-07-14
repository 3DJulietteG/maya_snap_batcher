
# _____________________IMPORTS_____________________

import re
import os
from maya import OpenMayaUI, cmds

# In Studio
# studio_import used to replace any studio import
import studio_import
import studio.atom as utils_atom
import studio.content_json as content_json
# Shotgrid API Keys
from studio_shotgrid import sg_chkusr, Shotgrid



# _____________________GLOBALS_____________________

LOGGER = studio_import.get_logger("maya_shot_confo_toolbox")
ATTRS = ["tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz", "v"]

# _____________________UTILS_____________________

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


def select_ctn(parent):
    """
    Select all _ctn with the given conditions
    :param parent: group under which to search for _ctn
    :return: list of _ctn
    """
    selection = []
    hierarchy = cmds.listRelatives(parent, ad=True)
    for each in hierarchy:
        if "_ctn" in each:
            if cmds.objectType(each) == "transform":
                selection.append(each)
    return selection


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


def delete_std(set_list):
    """
    Remove from scene the STD selected in the "Your current STD is:" widget in the UI
    :param set_list: list : set-dress(es) to remove
    """
    for each in set_list:
        if cmds.objExists(each):
            selection = cmds.ls(each)
            cmds.select(clear=True)
            cmds.select(selection)
            cmds.delete(selection)
            LOGGER.info(f"Removed {each} from scene")
        else:
            LOGGER.warning(f"Could not remove {each} from scene")

# _____________________MAIN_____________________

def import_std(content_json_file_path, atom_file_path) -> None:
    """
    Import wanted set-dress
    :param content_json_file_path: string : filepath to the set-dress json file
    :param atom_file_path: string : filepath to the set-dress atom file
    """
    json_content = content_json.read_json(content_json_file_path)

    for asset in json_content:
        asset_content = json_content[asset]
        process = content_json.ImportJson(
            asset_content["asset_type"],
            asset_content["asset_name"],
            asset_content["asset_padding"],
            asset_content["maya_namespace"],
        )
        new_ctn = process.launch_procedure()
        cmds.parent(new_ctn, f"|ALL|STG|{asset_content['asset_type']}")
        cmds.xform(
            new_ctn,
            translation=asset_content["translate"],
            rotation=asset_content["rotate"],
            scale=asset_content["scale"],
        )

    ctn_listing = cmds.ls("*_ctn", r=True)
    utils_atom.apply_atom(ctn_listing, atom_file_path)


def match_by_atom(namespace_new, namespace_old, new_std, old_std):
    """
    Match transforms for all matching _ctn between old set-dress and new set-dress
    :param namespace_new: string : New STD namespace
    :param namespace_old: string : Old STD namespace
    :param new_std: list : New set-dress and sets
    :param old_std: list : Old set-dress and sets
    """
    old_ctn = select_ctn(old_std)
    folder_path = os.path.dirname(cmds.file(query=True, sceneName=True))
    file_path = os.path.join(folder_path, "temporary_cached_values.atom")
    atom_export(old_ctn, file_path)
    new_ctn = select_ctn(new_std)
    for each in new_ctn:
        for attr in ATTRS:
            plug = f"{each}.{attr}"
            cmds.setAttr(plug, lock=False)
    atom_import(new_ctn, file_path, namespace_old, namespace_new)
    os.remove(file_path)
    return


def match_modification(new_std, old_std, old_set):
    """
    Find matching sets between old and new set-dresses and launch the match_by_atom function
    :param new_std: list : New set-dresses
    :param old_std: list : Old set-dresses
    :param old_set: list : Old sets
    """
    namespace_new = re.split(":", new_std[0])[0]
    for each_std in new_std:
        std_name = each_std.replace(namespace_new, "")
        if any(std_name in std for std in old_std):
            matching = [std for std in old_std if std_name in std][0]
            namespace_old = str(matching).split(std_name)[0]
            match_by_atom(namespace_new, namespace_old, each_std, matching)
        elif any(std_name in std for std in old_set):
            matching = [std for std in old_set if std_name in std][0]
            namespace_old = str(matching).split(std_name)[0]
            match_by_atom(namespace_new, namespace_old, each_std, matching)

    LOGGER.info("Done with conformation")


class ConfoUpdateShotgrid:
    """
    Update the shot info in Shotgrid to match the new set-dress
    :param wanted_set: string : wanted set-dress selected in the UI
    :return: ERROR : if multiple set-dress cast in SG
    # TODO : check with already existing SG scripts or create one
    """
    def __init__(self,project_name, env_name, wanted_set):
        # Init values
        studio_import.context(project=project_name, exec_env=env_name)
        self.project_name = studio_import.get("shotgrid.project")
        self.env_name = env_name

        self.sg_url = studio_import.get("shotgrid.url")
        self.sg_api_name = "MayaShotConfoToolbox"
        self.sg_api_key = os.getenv("MayaShotConfoToolbox")
        # Connections
        self.connect_to_server()
        # Get shot info
        scene_path = cmds.file(query=True, sceneName=True)
        scene_name = os.path.basename(scene_path)
        split_name = scene_name.split("_")
        episode, shot = split_name[1], split_name[3]
        sg_shot = self.sg_server_project.find_one(
            "Shot",
            [
                ["project", "name_is", f"PROJECT_NAME"],
                ["code", "is", f"{episode}_{shot}"],
            ],
            ["sg_set_dress"],
        )
        # Check STD casting for the shot
        if len(sg_shot["sg_set_dress"]) < 1:
            LOGGER.warning(f"No set-dress casted for {episode}_{shot}")
        elif len(sg_shot["sg_set_dress"]) > 1:
            LOGGER.warning(f"Multiple set-dress casted for {episode}_{shot}")
            return
        else:
            set_dress_name = sg_shot["sg_set_dress"][0]["name"]
            if set_dress_name == wanted_set:
                LOGGER.info(
                    f"The casted set-dress for {episode}_{shot} is already {wanted_set}"
                )
        # Get wanted STD entity
        std_entity = self.sg_server_project.find_one(
            "CustomEntity03",
            [
                ["project", "name_is", "PROJECT_NAME"],
                ["code", "is", wanted_set],
            ],
        )
        # Update shot info
        self.sg_server_project.update("Shot", sg_shot["id"], {"sg_set_dress": [std_entity]})
        LOGGER.info(f"Updated the set-dress casting in Shotgrid for {episode}_{shot}")

    ### CONNECTION
    def get_user(self):
        return sg_chkusr.ShotgridHumanUserInformations(
            shotgrid_url=self.sg_url,
            shotgrid_key=self.sg_api_key,
            human_user_fields=studio_import.get("shotgrid.fields.human_user"),
            script_name=self.sg_api_name,
        )

    def get_user_login(self):
        return self.get_user().infos["email"]

    def connect_to_server(self):
        self.sg_server = self.get_user().sg_server

        self.sg_server_project = Shotgrid(
            self.sg_url,
            api_key=self.sg_api_key,
            script_name=self.sg_api_name,
        )
        self.sg_server_project.project_name = self.project_name

        return self.sg_server_project, self.sg_server