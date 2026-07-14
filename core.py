# _____________________ROAD MAP_____________________

"""
Central batch process (snap and playblast)
"""

# _____________________IMPORTS_____________________

import os
import re
import time
from datetime import datetime
from typing import *
import maya.cmds as cmds
import maya.mel as mel
from copy import deepcopy
from pathlib import Path
import base_lib


# In Studio
# studio_import used to replace any studio import
import studio_import
import studio_shotgrid
import studio.atom as utils_atom
import studio.content_json as content_json

# Relatives
# Keep unused relatives import for recurrent call in snippet integration
from .manage_std import (import_std,
                         match_modification,
                         delete_std,
                         ConfoUpdateShotgrid)
from .utils import (check_assignation,
                    get_current_batch,
                    update_roller_vup,
                    replace,
                    remove_referenced,
                    get_std_info,
                    list_repath_error,
                    fix_repath,
                    change_set_dress,
                    atom_export,
                    atom_import,
                    )
# _____________________GLOBALS_____________________

SG_ENTITY = Dict[str, Any]
SHOTGRID_IO = studio_shotgrid.get_server().sg_con.connection
LOG = studio_import.get_logger("batch_snap_anim")

# constants
CAMERA_NAME = "camera_cam"
SG_ART_STATUS = ['sg_lead_status', 'sg_sup_status', 'sg_real_status', 'sg_client_status']
MAYA_CAMS = ["persp", "top", "front", "side", "left", "back", "bottom"]
BASE_CONTEXT = {
    "project_name": "PROJECT",
    "step": "",
    "task": "",
    "software": "MAYA",
    "trigram": "PRJT",
    "ext": "ma",
    "labels": [],
}
STEP_TASK = {
    "LAY" : ["layout"],
    "ANM" : ["anim", "animconfo", "fixing"]
}
IDLE_TIME = 240
TASK = str()
# _____________________UTILS_____________________

class StandalonePlayblastBuilder:
    """
    New instance of Studio PlayblastBuilder without any UI or popup window.
    Keeping the popup window for NoWorkRenderJsonFile error (to notice the missing shot and expect errors from farm latency)
    TASK : string() : task name
    """
    def __init__(
            self,
            scene_file_path,
            start,
            end,
            extra_name="",
            used_cam=studio_import.get("defaultCam"),
            snap=False,
            use_safe_action=True,
            use_overscan=False,
            use_wireframe=False,
            hide_image_planes=False,
            hide_locators=True,
            use_lights=False,
            use_occlusion=False,
            use_texture=True,
            use_two_sided=False,
            display_smoothness=False,):
            # Set default values
            self.project_name = studio_import.playblast_burning.project_value()
            self.ffmpeg_id = None
            self.use_default_material = False

            # Initiate all elements needed. Will be overwritten if we are in a snap playblast
            self.scene_file_path = scene_file_path
            self.start = start
            self.end = end
            extra_name = studio_import.normalize(extra_name)
            self.extra_name = f"_{extra_name}" if extra_name else extra_name
            self.used_cam = used_cam
            self.snap = snap

            # Set class user settings in self
            self.use_safe_action = use_safe_action
            self.use_overscan = use_overscan
            self.use_wireframe = use_wireframe
            self.hide_image_planes = hide_image_planes
            self.hide_locators = hide_locators
            self.use_lights = use_lights
            self.use_occlusion = use_occlusion
            self.use_texture = use_texture
            self.use_two_sided = use_two_sided
            self.display_smoothness = display_smoothness

            # Create dict to store UI user values before playblast
            self.user_values_to_restore_dict = dict()
            self.elements_to_revert = [
                "lights",
                "locators",
                "displayTextures",
                "wireframeOnShaded",
                "useDefaultMaterial",
                "twoSidedLighting",
                "nurbsCurves",
                "displayAppearance",
            ]

            # Create dict to store hardware renderning user values before playblast
            self.hardware_rendering_globals_settings_to_restore_dict = dict()
            self.hardware_rendering_globals_attributes = [
                "ssaoEnable",
                "lineAAEnable",
                "multiSampleEnable",
            ]

            self.image_plane_to_show = list()
            self.frustum_cam = []
            self.refs_to_reload = []
            self.action = ""

            self.all_cameras = []
            self.hud_elements_to_restore = dict()
            self.hud_elements = []
            self.pre_playblast_safe_action = dict()
            self.alpha_cut_prepass = None
            self.meshes_already_smoothed = dict()

            self.all_cameras = list()
            for cam in cmds.listCameras():
                hierarchy = cmds.listRelatives(cam, fullPath=True)[0]
                if "TRASH" in hierarchy:
                    continue
                else:
                    self.all_cameras.append(cam)

            # Force settings based on parametric if snap mode is enabled
            if self.snap and not studio_import.get("useSetup"):
                self.set_prod_parameters()

    def _store_user_values(self, panel):
        # Store Viewport settings
        for element in self.elements_to_revert:
            self.user_values_to_restore_dict[element] = eval(
                f"cmds.modelEditor('{panel}', query=True, {element}=True)"
            )

        # Store Hardware Rendering Globals Settings
        for attribute in self.hardware_rendering_globals_settings_to_restore_dict:
            self.hardware_rendering_globals_attributes["sceneOcclusion"] = cmds.getAttr(
                f"hardwareRenderingGlobals.{attribute}"
            )
            self.hardware_rendering_globals_attributes["lineAAEnable"] = cmds.setAttr(
                f"hardwareRenderingGlobals.{attribute}"
            )
            self.hardware_rendering_globals_attributes["multiSampleEnable"] = (
                cmds.setAttr(f"hardwareRenderingGlobals.{attribute}")
            )

        # Store HUD settings
        self.hud_elements = cmds.headsUpDisplay(listHeadsUpDisplays=True)
        self.hud_elements_to_restore = list()
        for active in self.hud_elements:
            is_visible = cmds.headsUpDisplay(active, query=True, visible=True)
            if is_visible:
                self.hud_elements_to_restore.append(active)

        # Store camera values
        self.camera_datas_to_restore = dict()
        for camera in self.all_cameras:
            self.camera_datas_to_restore[camera] = dict()

            # Store specific datas
            camera_datas = [
                "panZoomEnabled",
                "displayFilmGate",
                "displayResolution",
                "displayGateMask",
                "displaySafeAction",
                "displaySafeTitle",
                "overscan",
            ]
            for camera_data in camera_datas:
                self.camera_datas_to_restore[camera][camera_data] = eval(
                    f"cmds.camera('{camera}', query=True, {camera_data}=True)"
                )

        # Store meshes smooth mode
        self.meshes_smooth_mode_dict = dict()
        for mesh in cmds.ls(type="mesh"):
            self.meshes_smooth_mode_dict[mesh] = cmds.getAttr(
                f"{mesh}.displaySmoothMesh"
            )


    def _restore_user_values(self, panel):
        # Restore user Viewport parameters
        cmds.modelEditor(panel, edit=True, **self.user_values_to_restore_dict)

        cmds.camera(self.used_cam, edit=True, displaySafeAction=True)

        # restore camera datas
        for camera in self.all_cameras:
            cmds.camera(camera, edit=True, **self.camera_datas_to_restore[camera])

        # show imagePlanes
        if self.image_plane_to_show:
            for relative in self.image_plane_to_show:
                if "displayMode" in cmds.listAttr(relative):
                    cmds.setAttr(f"{relative}.displayMode", 3)

        # Restore Hardware Rendering Globals Settings
        for attribute in self.hardware_rendering_globals_settings_to_restore_dict:
            cmds.setAttr(
                f"hardwareRenderingGlobals.{attribute}",
                self.hardware_rendering_globals_settings_to_restore_dict[attribute],
            )

        # Restore HUD
        for hud_element in self.hud_elements_to_restore:
            cmds.headsUpDisplay(hud_element, edit=True, visible=True)

        # Restore meshes smooth mode
        for mesh in self.meshes_smooth_mode_dict:
            cmds.setAttr(
                f"{mesh}.displaySmoothMesh", self.meshes_smooth_mode_dict[mesh]
            )


    def prepare_playblast(self, panel):
        # get elements from the scene for reset
        self._store_user_values(panel=panel)

        # If we use the texture, disable default material, enable alphaCutPrepass
        if self.use_texture:
            self.use_default_material = False
            self.alpha_cut_prepass = cmds.getAttr(
                "hardwareRenderingGlobals.alphaCutPrepass"
            )
            cmds.setAttr("hardwareRenderingGlobals.alphaCutPrepass", True)

            # Reload all textures and regenerate UV tile preview
            cmds.ogs(reloadTextures=True)
            file_nodes = cmds.ls(type="file")
            for file_node in file_nodes:
                if (
                    cmds.getAttr(file_node + ".uvTilingMode") != 0
                    and cmds.getAttr(file_node + ".uvTileProxyQuality") != 0
                ):
                    cmds.ogs(regenerateUVTilePreview=file_node)


        # set for Project
        if studio_import.playblast_burning.project_value() in ["PROJECT"]:
            cmds.setAttr("hardwareRenderingGlobals.lineAAEnable", True)
            cmds.setAttr("hardwareRenderingGlobals.multiSampleEnable", True)

        # Set viewport regarding wanted setup
        cmds.modelEditor(
            panel,
            edit=True,
            nurbsCurves=False,
            dimensions=False,
            handles=False,
            lights=self.use_lights,
            locators=not self.hide_locators,
            displayTextures=self.use_texture,
            displayAppearance="smoothShaded",
            wireframeOnShaded=self.use_wireframe,
            useDefaultMaterial=self.use_default_material,
            twoSidedLighting=self.use_two_sided,
        )

        # Update cameras
        for cam in self.all_cameras:
            # Regarding display safe action
            cmds.camera(cam, edit=True, displaySafeAction=self.use_safe_action)
            cmds.camera(cam, edit=True, displaySafeTitle=False)

            # Disable panZoom
            cmds.camera(cam, edit=True, panZoomEnabled=False)

        # Hide all cams frustum
        for camera in self.all_cameras:
            if camera not in MAYA_CAMS:
                if self.project_name in ["PROJECT"]:
                    cmds.setAttr(f"{camera.partition(':')[0]}:info_ctrl.Frustum", 0)
                elif self.project_name in ["OTHER_PROJECT"]:
                    cmds.setAttr(
                        f"{camera.partition(':')[0]}:cam_holder_ctrl.FrustumVisibility",
                        0,
                    )
                else:
                    raise NotImplementedError(
                        "This project is not supported yet. Please report the incident."
                    )
            else:
                cmds.setAttr(f"{camera}.displayCameraFrustum", 0)

        # Show/hide image planes
        image_planes = cmds.ls(type="imagePlane")

        for image_plane in image_planes:
            cmds.setAttr(f"{image_plane}.visibility", not self.hide_image_planes)

        # add viewport occlusion
        if self.use_occlusion:
            cmds.setAttr("hardwareRenderingGlobals.ssaoEnable", True)

        # Apply display smoothness
        if self.display_smoothness:
            meshes = cmds.ls(type="mesh")
            for mesh in meshes:
                cmds.setAttr(f"{mesh}.displaySmoothMesh", 2)


    def set_prod_parameters(self):
        """Use parameters' elements if we are in the snap playblast mode"""
        self.use_safe_action = studio_import.get(
            "studio_import.config.ui.use_safe_action"
        )
        self.use_overscan = studio_import.get(
            "studio_import.config.ui.use_overscan"
        )
        self.use_wireframe = studio_import.get(
            "studio_import.config.ui.use_wireframe"
        )
        self.hide_image_planes = studio_import.get(
            "studio_import.config.ui.hide_image_plane"
        )
        self.hide_locators = studio_import.get(
            "studio_import.config.ui.hide_locators"
        )
        self.use_lights = studio_import.get(
            "studio_import.config.ui.use_lights"
        )
        self.use_occlusion = studio_import.get(
            "studio_import.config.ui.use_occlusion"
        )
        self.use_texture = studio_import.get(
            "studio_import.config.ui.use_textures"
        )
        self.use_two_sided = studio_import.get(
            "studio_import.config.ui.use_two_sided"
        )
        self.display_smoothness = studio_import.get(
            "studio_import.config.ui.display_smoothness"
        )


    def execute(self, force=False):
        """Will prepare the scene, launch the playblast and reset the scene"""

        # Force camera view
        self.change_camera_view()

        # Defines if we're working on SHOT or SEQUENCE
        context = self.get_context()[0]
        if context == "SEQUENCES":
            sequence_time = True
            use_trax_sounds = True
        else:
            sequence_time = False
            use_trax_sounds = False

        # Fix bad rig evaluation
        cmds.currentTime(0)
        cmds.currentTime(1)

        # Make sure we have the right panel
        cmds.setFocus("modelPanel4")
        panel = cmds.getPanel(withFocus=True)

        # Get current cam resolution and overscan for reset
        camera_display_resolution = cmds.getAttr(f"{self.used_cam}.displayResolution")
        camera_overscan = cmds.getAttr(f"{self.used_cam}.overscan")

        # hide unwanted elements
        self.prepare_playblast(panel)

        # Generate UV Tile Previews (renderer : viewport 2.0)
        cmds.ogs(reloadTextures=True)
        file_nodes = cmds.ls(type="file")
        for file_node in file_nodes:
            if (
                cmds.getAttr(file_node + ".uvTilingMode") != 0
                and cmds.getAttr(file_node + ".uvTileProxyQuality") != 0
            ):
                cmds.ogs(regenerateUVTilePreview=file_node)

        if self.snap:
            for hud in self.hud_elements:
                cmds.headsUpDisplay(hud, edit=True, visible=False)
        else:
            # Will add the wanted burnins
            studio_import.playblast_burning.create_burnins_artist(start=self.start, end=self.end)

        if self.use_overscan:
            for camera in self.all_cameras:
                cmds.camera(
                    camera,
                    e=True,
                    displayFilmGate=False,
                    displayResolution=True,
                    displayGateMask=True,
                    ovr=1.4,
                )
        else:
            for camera in self.all_cameras:
                cmds.camera(
                    camera,
                    e=True,
                    displayFilmGate=False,
                    displayResolution=False,
                    displayGateMask=False,
                    ovr=1,
                )

        playblast_type_to_format_and_compression = {
            "image": ("image", "jpg"),
            "video": ("qt", "jpeg"),
        }

        fullpath = Path(self.scene_file_path)
        format, compression = playblast_type_to_format_and_compression["video"]
        scene_name = self.scene_file_path
        section = studio_import.get_section_from_path(scene_name, "work_path")
        try:
            # get audio specific project audio name
            audio_node = studio_import.get_audio_node_name(section, scene_name)
            assert audio_node in cmds.ls(type="audio")
            playback_slider = mel.eval("$tmpVar=$gPlayBackSlider")
            cmds.timeControl(
                playback_slider, e=True, sound=audio_node, displaySound=True
            )
        except (AssertionError, KeyError):
            print(
                "Could not get shot information, trying with currently selected sound node in timeline"
            )

        audio_node = cmds.timeControl("timeControl1", q=True, sound=True)
        # Will set full path, with extra name (comment in the UI)
        playblast_path = (
            fullpath.parent / "PLAYBLAST" / "WIP" / f"{fullpath.stem}{self.extra_name}"
        )


        # If overwrite or no existing path : just continue the process
        playblast_path = cmds.playblast(
            startTime=self.start,
            endTime=self.end,
            format=format,
            filename=str(playblast_path),
            sequenceTime=sequence_time,
            clearCache=True,
            viewer=False,
            showOrnaments=True,
            percent=100,
            compression=compression,
            quality=studio_import.get("playblastQuality"),
            sound=audio_node,
            useTraxSounds=use_trax_sounds,
            offScreen=True,
            widthHeight=[1920, 1080],
            forceOverwrite=False,
        )

        # Reset cams
        cmds.camera(
            self.used_cam,
            e=True,
            displayResolution=camera_display_resolution,
            displayGateMask=camera_display_resolution,
            overscan=camera_overscan,
        )

        # Show everything again
        self._restore_user_values(panel)

        # Restore image plane visibility
        image_planes = cmds.ls(type="imagePlane")
        if self.hide_image_planes:
            for image_plane in image_planes:
                cmds.setAttr(f"{image_plane}.visibility", 1)

        return playblast_path


    def launch_ffmpeg_process(self, force=False):
        """Snap playblast call"""
        playblast_path = None

        # Launch the playblast in Maya
        playblast_path = self.execute(force=force)

        if not playblast_path:
            return
        playblast_path = Path(playblast_path).with_suffix(".mov")
        scene_path = self.scene_file_path

        section = studio_import.get_section_from_path(scene_path, "work_path")

        info = studio_import.extract(section, "work_path", scene_path)
        info["ext"] = "mov"
        info["MEDIA"] = "PLAYBLAST"

        destination_file_path = studio_import.make(
            section, "work_render_mp4_path", info
        )
        destination_dir_path = studio_import.make(section, "work_render_path", info)

        if not os.path.exists(destination_dir_path):
            os.makedirs(destination_dir_path)

        info["task"] = TASK
        studio_import.create_json(info["task"], int(info["version"]), destination_dir_path)

        # Apply burnings & create job
        deadline = studio_import.get_deadline()
        fps = studio_import.get("fps")

        input_args = ""
        output_args = self.get_burning_ffmpeg_output_args(
            fps=fps, start=int(self.start), end=int(self.end)
        )

        job_info, plug_info = studio_import.setup_ffmpeg_job(
            str(playblast_path),
            input_args,
            str(destination_file_path),
            output_args,
            end=1,
        )

        self.ffmpeg_id = deadline.Jobs.SubmitJob(job_info, plug_info).get("_id")

        return self.ffmpeg_id


    def change_camera_view(self):
        """Focus all views on the selected camera"""
        panels = cmds.getPanel(allPanels=True)
        for panel in panels:
            if "modelPanel" not in panel:
                continue
            cam = cmds.modelPanel(panel, query=True, camera=True)
            if cam:
                cmds.modelPanel(panel, edit=True, camera=self.used_cam)


    def get_burning_ffmpeg_output_args(
            self, fps, start, end, cam=None, forced_profile=None
    ):
        """Provide all burnings values"""
        base_text_filters = studio_import.playblast_burning.set_args_burnin_snap(start, end, cam=cam)

        timecode = (
            f"{time.strftime('%H:%M:%S', time.gmtime(start // fps))}:{start % fps}"
        )

        font_size = 30
        font_file = "Calibri-Regular.ttf"
        font_color = "#bfbfbf"
        box_color = "black@0.5"
        box_border_width = "5"
        filters = [
            f"drawtext='{base_text_filter}:box=1:boxcolor={box_color}:boxborderw={box_border_width}:fontcolor={font_color}:fontsize={font_size}:fontfile={font_file}'"
            for base_text_filter in base_text_filters
        ]
        formatted_filters = ",".join(map(repr, filters))

        profile = forced_profile or "high"

        return f"-c:v libx264 -profile:v {profile} -map v:0 -timecode {timecode} -c:a copy -map a? -vf {formatted_filters}"


    def get_context(self):
        parts = self.scene_file_path.split(os.sep)

        section = key = None
        if "Assets" in parts:
            section = "ASSETS"
            if "work" in parts:
                key = "work_path"
            elif "snap" in parts:
                key = "snap_path"
            elif "pub" in parts:
                key = "publish_path"
        elif "Shots" in parts:
            for i in parts:
                if "sh" in i:
                    section = "SHOTS"
                    key = "shot_file_path"
            if section is None:
                section = "SEQUENCES"
                key = "sequence_file_path"
        elif "SetDresses" in parts:
            section = "SETDRESSES"
            if "work" in parts:
                key = "work_path"
            elif "snap" in parts:
                key = "snap_path"
            elif "pub" in parts:
                key = "publish_path"
        return section, key

def get_sg_project() -> SG_ENTITY:
    """Return Shotgrid current project entity."""
    return {"type": "Project", "id": studio_import.get("shotgrid.id")}

class NoWorkRenderJsonFileError(Exception):
    pass

def get_relevant_sg_task_from_json(work_render_dir_path: str) -> str:
    """Get the applicable Shotgrid task from the work render json filename, if existing, inferred from the current work render dir path.

    :param work_render_dir_path: Path to the work render directory of a specific work scene
    :type work_render_dir_path: str
    :raises NoWorkRenderJsonFileError: If no single properly formatted work render json file could be found in the work render folder
    :return: Name of the applicable Shotgrid task
    :rtype: str
    """
    current_pm_section = studio_import.get_section_from_path(input_path=work_render_dir_path, key="work_render_path")
    work_render_json_filename_regex_pattern = r"task_[a-z]+_v\d{3}\.json"
    eligible_work_render_json_file_names = []
    if os.path.isdir(work_render_dir_path):
        for dir_element in os.listdir(work_render_dir_path):
            if os.path.isfile(os.path.join(work_render_dir_path, dir_element)) and re.fullmatch(
                    pattern=work_render_json_filename_regex_pattern, string=dir_element):
                eligible_work_render_json_file_names.append(dir_element)

        # Only one single work render json file is expected to be found in the current work render directory
        if len(eligible_work_render_json_file_names) != 1:
            raise NoWorkRenderJsonFileError(
                f"No work render json file could be found at {work_render_dir_path!r} (no proper SG task could therefore be inferred from the current context).")

        else:
            specific_task = studio_import.extract(section=current_pm_section, key="work_render_json_filename",
                                                     path=eligible_work_render_json_file_names[0]).get("specific_task")
            return specific_task

    else:
        raise NoWorkRenderJsonFileError(
            f"No work render json file could be found at {work_render_dir_path!r} (no proper SG task could therefore be inferred from the current context).")

def get_last_file_path(name):
    """
    Get the last file path of a given shot name
    :param name: string() : Shot name (format: ep000_sq0000_sh0000)
    """
    episode, sequence, shot = name.split("_")
    tmp_ctx = deepcopy(BASE_CONTEXT)
    tmp_ctx["episode"] = episode
    tmp_ctx["sequence"] = sequence
    tmp_ctx["shot"] = shot

    tmp_work_dir_path = studio_import.make("SHOTS", "work_folder", tmp_ctx)
    tmp_work_files = sorted([x.path for x in os.scandir(tmp_work_dir_path) if x.is_file()])
    tmp_ctx["version"] = tmp_work_files[-1][-6:-3]
    tmp_file_path = studio_import.make("SHOTS", "work_path", tmp_ctx)
    return tmp_ctx, tmp_file_path, tmp_work_dir_path, tmp_work_files

def load_scattering_content():
    """
    Load scattering content if existing scattering for environment
    """
    # Gather staging content
    staging_content = studio_import.get_staging_content(
        target_transform="ALL|STG",
        check_visibility=False,
    )
    # Filter staging content to keep only ENV and SET elements
    filtered_staging_content = [
        stg_obj
        for stg_obj in staging_content
        if type(stg_obj) in [studio_import.EnvObject, studio_import.SetObject]
    ]
    # Get CTN transform from filtered staging content
    ctn_list = [stg_obj.transform for stg_obj in filtered_staging_content]
    # Initialise scattering manager and get ScatterObject list
    scattering_manager = studio_import.ScatteringManagerModel()
    scattering_manager.get_scatters(ctn_list=ctn_list)
    # Enable Scatter in scene
    # Scattering manager should handle all missing content operations
    for scatter_obj in scattering_manager.scatter_list:
        scatter_obj: studio_import.ScatterObject
        scatter_obj.loaded = True

def execute_snap(ctx):
    """
    Launching full snap process with split between playblast and snap execution
    :param ctx: dictionary{} : dictionary containing all shot information
    :global IDLE_TIME : integer() : idle time (in second) between the launch of the burning process and the snap execution.
                                    Can be increased or decreased in relation to the farm congestion
    """
    scene_name = cmds.file(sn=True, query=True)
    if "Shots" in scene_name:
        section = studio_import.get_section_from_path(cmds.file(query=True, sceneName=True), 'work_path')
        if section == 'SHOTS':
            scene_data = studio_import.get_opened_scene_data(section="SHOTS", key="work_file")
            scene_task = scene_data.get("task")
            scene_step = scene_data.get("step")
            if scene_task in ["buildanimation", "block", "anim", "animol", "exportfur"]:
                specific_task = None
                if scene_task in ["block", "anim", "animol"]:
                    if scene_task == "anim":
                        #PLayblast
                        sg_obj = studio_import.get_server()
                        sg_instance = sg_obj.sg_con.connection
                        # query shot on sg
                        sg_shot = sg_instance.find_one(
                            'Shot',
                            filters=[
                                ['project', 'name_is', sg_obj.sg_con._get_project_name()],
                                ['code', 'is', f"{ctx['episode']}_{ctx['shot']}"],
                                ['sg_sequence.Sequence.code', 'is', f"{ctx['episode']}_{ctx['sequence']}"],
                                ['sg_sequence.Sequence.episode.Episode.code', 'is', ctx['episode']],
                            ],
                            fields=['sg_shot_in', 'sg_shot_out'],
                        )

                        deadline_instance = studio_import.get_deadline()
                        work_path = studio_import.make("SHOTS", "work_path", ctx)
                        cam_namespace = f"TPL_{studio_import.get('maya.animation_camera')}_{ctx['shot']}"
                        cam = f"{cam_namespace}:{CAMERA_NAME}"
                        playblaster = StandalonePlayblastBuilder(
                            scene_file_path=work_path,
                            start=sg_shot["sg_shot_in"],
                            end=sg_shot["sg_shot_out"],
                            snap=True,
                            used_cam=cam,
                        )
                        playblast_job_id = playblaster.launch_ffmpeg_process(force=True)
                        studio_import.log_variable(LOG, playblast_job_id)
                        LOG.info("Going to sleep waiting for presentation rendering")
                        time.sleep(IDLE_TIME)
                        LOG.info("Time to wake up : Go!")
                        #Snap
                        try:
                            pm_context = studio_import.extract(section, "work_path", scene_data["scene_full_path"])
                        except:
                            pm_context = studio_import.extract(section, "work_path_extra",
                                                                  scene_data["scene_full_path"])
                        pm_context["MEDIA"] = "PLAYBLAST"

                        work_render_dir_path = studio_import.make(section="SHOTS", key="work_render_path",
                                                                     context=pm_context)

                        specific_task = get_relevant_sg_task_from_json(work_render_dir_path=work_render_dir_path)

                    _import_path_arg = [f"studio_import.process.shot.anim.snap",
                                        f"{os.environ.get('PROJECT_NAME').lower()}.process.shot.anim.snap"]
                    _callable_name_arg = "SnapAnim"

                else:

                    _import_path_arg = [f"studio_import.process.shot.{scene_task}.snap",
                                        f"{os.environ.get('PROJECT_NAME').lower()}.process.shot.{scene_task}.snap"]
                    _callable_name_arg = f"Snap{scene_task.capitalize()}"

                process = base_lib.module_override(import_path=_import_path_arg, callable_name=_callable_name_arg)
                relevant_task = scene_task if not specific_task else specific_task
                process(user_interface_class=studio_import.GuiDialog).execute(
                    task_path_list=[
                        f"{scene_data.get('episode')}/{scene_data.get('sequence')}/{scene_data.get('shot')}-{scene_step}:{relevant_task}"
                    ]
                )
            else:
                raise NotImplementedError
        else:
            cmds.error("Unable to retrieve entity.")

def batch_snap(snap_shot_lst,selected_task,selected_vup, add_scattering, add_process):
    """
    Launch snap and additional process for every shot in list.
    Create log folder to follow the batch progression
    :param snap_shot_lst: list(string) : list of selected shots
    :param selected_task: string() : selected task
    :param selected_vup: boolean() : choose to launch vup
    :param add_scattering: boolean() : choose to enable scattering on grass patch
    :param add_process: string() : written additional subprocesses
    """
    # Start building context with selected task
    selected_step = str()
    for step in STEP_TASK:
        for items in STEP_TASK.get(step):
            if items == selected_task:
                selected_step = step
    if selected_step:
        global BASE_CONTEXT
        BASE_CONTEXT["step"]=selected_step
        if selected_step == "ANM":
            BASE_CONTEXT["task"]="anim"
        else:
            BASE_CONTEXT["task"]=selected_task
    else:
        LOG.error("Step not found")
        return

    # Update global TASK with selected_task
    global TASK
    TASK = selected_task

    # Create log folder
    day_batch_folder = datetime.now().strftime('%Y_%m_%d')
    batch_folder = Path.home()/"BATCH"
    batch_folder.mkdir(parents=True, exist_ok=True)
    day_batch_path = batch_folder / day_batch_folder
    day_batch_path.mkdir(parents=True, exist_ok=True)
    log_path, batch_number = get_current_batch(day_batch_path)
    with open(log_path, 'w') as file:
        file.writelines([f"List of shots running on {day_batch_folder} in {batch_number} \n",])

    # Execute process on every shot
    for shot in snap_shot_lst:
        ctx, file_path, work_dir_path, work_files = get_last_file_path(shot)
        cmds.file(file_path, o=True, force=True)
        studio_import.make_increment(file_path)
        ctx, file_path, work_dir_path, work_files = get_last_file_path(shot)
        cmds.file(file_path, o=True, force=True)
        # Set renderer to alpha cut
        cmds.setAttr("hardwareRenderingGlobals.transparencyAlgorithm", 1)
        cmds.setAttr("hardwareRenderingGlobals.alphaCutPrepass", 1)
        # Check assignation
        check_assignation(TASK)
        # Rebuild STD if temporary set dress
        if "TEMP_STD_001RN" in cmds.ls(references=True):
            # Delete existing ctn
            ctn_lst = []
            hierarchy = cmds.listRelatives("STG", ad=True)
            for each in hierarchy:
                if "_ctn" in each:
                    if cmds.objectType(each) == "transform":
                        if cmds.referenceQuery(each, isNodeReferenced=True):
                            continue
                        else:
                            ctn_lst.append(each)
            cmds.delete(ctn_lst)
            # Rebuild set dress
            LOG.info("Launching Setdress Reconstruction...")
            reference_std_infos = studio_import.get_config_nodes_attribute(
                "referenced_std_info__cfg", "referenced_from"
            )
            entity_name = reference_std_infos["STD_name"]
            current_version = reference_std_infos["STD_version"]
            # Get reference infos
            reference_node = "TEMP_STD_001RN"
            try:
                temp_std_path = cmds.referenceQuery(reference_node, filename=True)
            except Exception as e:
                LOG.error(f"Raises error {e}: Could not retrieve reference's path")
                raise
            cmds.file(temp_std_path, removeReference=True)
            atom_std_path = temp_std_path.replace(".ma", ".atom")
            # Get STD infos
            json_dir, atom_dir, base_context = get_std_info(str(entity_name), current_version)
            # Load corresponding STD
            json_content = content_json.read_json(json_dir)
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
            utils_atom.apply_atom(ctn_listing, atom_dir)
            utils_atom.apply_atom(ctn_listing, atom_std_path)
            # Delete config node
            if cmds.objExists("referenced_std_info__cfg"):
                cmds.delete("referenced_std_info__cfg")
            LOG.info(f"Success reloading {entity_name}, version {current_version}")
            try:
                cmds.delete("TEMP_STD_001RNfosterParent1")
            except Exception as e:
                LOG.info(f"No remaining foster parent")
            else:
                LOG.info(f"Deleted remaining foster parent")
        else:
            try:
                cmds.delete("referenced_std_info__cfg")
            except Exception as e:
                LOG.info(f"No temporary set dress config node remaining")
            else:
                LOG.info(f"Deleted remaining temporary set dress config node")
        try:
            cmds.delete("TEMP_STD_001RNfosterParent1")
        except Exception as e:
            LOG.info(f"No remaining foster parent")
        else:
            LOG.info(f"Deleted remaining foster parent")
        # Change Set dress
        # VUP
        if selected_vup:
            section, task = studio_import.get_context()
            collector = studio_import.get_collector(section, task)
            controller = studio_import.VersionUpdaterControler(collector)
            try:
                result = controller.raise_all_versions()
            except Exception as e:
                with open(log_path, 'a') as file:
                    file.writelines([f"{shot}  -->  COULD NOT EXECUTE VUP\n", ])
                    continue
        # Others
        # Repath error
        error_path, error_nodes = list_repath_error()
        if not error_path:
            LOG.info(f"No existing repath error in {shot}")
        else:
            for each in error_nodes:
                LOG.info(f"Cleaning repath error for {each}")
            errors_node, errors_path = fix_repath()
            if errors_node:
                LOG.info(f"Remaining errors for {errors_node}")
        # Hide ToyCube
        hierarchy = cmds.listRelatives("STG", ad=True)
        for each in hierarchy:
            if "_ctn" in each:
                if cmds.objectType(each) == "transform":
                    if "ToyCube" in each:
                        cmds.setAttr(f"{each}.visibility", 0)
        # Add process
        if add_process:
            exec(add_process)
        # Scattering
        if add_scattering:
            load_scattering_content()
        # Snap
        cmds.select(clear=True)
        cmds.file(save=True)
        # Logs
        if "TEMP_STD_001RN" in cmds.ls(references=True):
            with open(log_path, 'a') as file:
                file.writelines([f"{shot}  -->  TEMP_STD COULD NOT SEND TO SNAP\n", ])
            continue
        with open(log_path, 'a') as file:
            file.writelines([f"{shot}  -->  SENT TO SNAP\n", ])
        execute_snap(ctx)

# _____________________MAIN SCRIPT_____________________


# _____________________TEMP_____________________

