#_____________________ROAD MAP_____________________

"""
All windows and interfaces
"""

#_____________________IMPORTS_____________________

from functools import partial
from PySide2 import QtCore, QtWidgets

from .utils import (get_shot_list,
                    get_episode_list)

from .core import batch_snap


#_____________________MAIN SCRIPT_____________________

class BatcherMainWindow(QtWidgets.QMainWindow):
    """
    Main window for batcher
    """
    qmw_instance = None

    @classmethod
    def show_ui(cls):
        """
        Create new instance or show it, if it was hidden or dropped
        """
        if not cls.qmw_instance:
            cls.qmw_instance = BatcherMainWindow()
        else:
            cls.qmw_instance.close()
            cls.qmw_instance = BatcherMainWindow()

    def set_pop_up_window(self):
        self.popup = PopUpWindow(self.snap_shot_lst, self.selected_task, self.selected_vup, self.add_scattering, self.add_process)

    def __init__(self):
        """
        Initialize the main batcher window
        """
        super().__init__()
        # Variable
        self.snap_shot_lst = list()
        self.selected_task = ""
        self.selected_vup = False
        self.add_scattering = False
        self.add_process = False

        # Window
        self.setWindowTitle("Who you gonna call ?")
        self.resize(700, 400)
        main_layout = QtWidgets.QGridLayout()
        main_layout.setAlignment(QtCore.Qt.AlignTop)

        # Iterate LaunchFunctions
        self.launch_functions = LaunchFunctions(self, PopUpWindow)

        # Episode Layout
        self.episode_box = QtWidgets.QGroupBox("EPISODES")
        episode_upper_layout = QtWidgets.QVBoxLayout()
        episode_layout = QtWidgets.QVBoxLayout()
        episode_lst = get_episode_list()
        for episode_nb in episode_lst:
            ep_btn = QtWidgets.QPushButton(f"EPISODE {episode_nb}")
            ep_btn.clicked.connect(partial(self.launch_functions.get_episode_info, episode_nb = f"ep{episode_nb}"))
            episode_layout.addWidget(ep_btn)
        ep_widget = QtWidgets.QWidget()
        ep_widget.setLayout(episode_layout)
        # scroll area
        ep_scroll_area = QtWidgets.QScrollArea()
        ep_scroll_area.setWidgetResizable(True)
        ep_scroll_area.setWidget(ep_widget)
        episode_upper_layout.addWidget(ep_scroll_area)
        self.episode_box.setLayout(episode_upper_layout)

        # Sequence/Shot Layout
        #Variable
        self.selection_box = QtWidgets.QGroupBox("SEQUENCES/SHOTS")
        selection_upper_layout = QtWidgets.QVBoxLayout()
        self.selection_layout = QtWidgets.QVBoxLayout()
        sl_widget = QtWidgets.QWidget()
        sl_widget.setLayout(self.selection_layout)
        self.shot_tree_widget = QtWidgets.QTreeWidget()
        self.shot_tree_widget.setColumnCount(2)
        self.shot_tree_widget.setHeaderLabels(["Sequences", "Shots"])
        self.shot_tree_widget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.shot_tree_widget.itemSelectionChanged.connect(self.launch_functions.update_shot_count)
        self.selection_layout.addWidget(self.shot_tree_widget)
        # scroll area
        sl_scroll_area = QtWidgets.QScrollArea()
        sl_scroll_area.setWidgetResizable(True)
        sl_scroll_area.setWidget(sl_widget)
        selection_upper_layout.addWidget(sl_scroll_area)
        self.selection_box.setLayout(selection_upper_layout)

        # Info Layout
        info_layout = QtWidgets.QGridLayout()
        self.task_box = QtWidgets.QComboBox()
        self.task_box.addItems(["layout", "anim", "animconfo", "fixing"])
        self.task_box.setCurrentIndex(2)
        self.count_line = QtWidgets.QLineEdit()
        self.count_line.setText("0")
        self.count_line.setReadOnly(True)
        info_layout.addWidget(QtWidgets.QLabel("Selected Task :"), 0, 3, 1, 1)
        info_layout.addWidget(self.task_box, 0, 4, 1, 1)
        info_layout.addWidget(QtWidgets.QLabel("Selection count :"), 0, 5, 1, 1)
        info_layout.addWidget(self.count_line,0,6,1,1)


        # Launch layout
        launch_layout = QtWidgets.QGridLayout()
        launch_layout.addWidget(QtWidgets.QLabel("Batch optional processes :"), 0,0,1,1)
        self.vup_checkbox = QtWidgets.QCheckBox("Raises all versions ?")
        self.scattering_checkbox = QtWidgets.QCheckBox("Add scattering ?")
        self.add_checkbox = QtWidgets.QCheckBox("Add Python snippets ?")
        self.launch_btn = QtWidgets.QPushButton("GhostBusters!")
        self.launch_btn.clicked.connect(self.launch_functions.sub_check_launch_batch_snap)
        launch_layout.addWidget(self.vup_checkbox,0,1,1,1)
        launch_layout.addWidget(self.scattering_checkbox,0,2,1,1)
        launch_layout.addWidget(self.add_checkbox,0,3,1,1)
        launch_layout.addWidget(self.launch_btn,1,0,1,5)

        # Main Layout
        main_layout.addWidget(self.episode_box,0,0,7,3)
        main_layout.addWidget(self.selection_box, 0, 3, 7, 7)
        main_layout.addLayout(info_layout,8,0,1,10)
        main_layout.addLayout(launch_layout,9,0,2,10)

        self.dialogs = list()
        self.tools_widget = QtWidgets.QWidget()
        self.tools_widget.setLayout(main_layout)
        self.setCentralWidget(self.tools_widget)

        self.popup = None
        self.set_pop_up_window()

class PopUpWindow(QtWidgets.QMainWindow):
    """
    Pop up window for batcher to execute snippets
    """
    # Inherited by class MayaPopUpWindow
    def __init__(self, snap_shot_lst, selected_task, selected_vup, add_scattering, add_process):
        """
        Initialize the pop-up window
        :param snap_shot_lst: list(string) : list of selected shots
        :param selected_task: string() : selected task
        :param selected_vup: boolean() : choose to launch vup
        :param add_scattering: boolean() : choose to enable scattering on grass patch
        :param add_process: boolean() : choose whether to add subprocesses
        """
        super().__init__()
        # Variable
        self.snap_shot_lst = snap_shot_lst
        self.selected_task = selected_task
        self.selected_vup = selected_vup
        self.add_scattering = add_scattering
        self.add_process = add_process
        # Window
        self.setWindowTitle("Add snippet")
        self.resize(800, 250)
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setAlignment(QtCore.Qt.AlignTop)
        main_layout.addSpacing(5)

        # Iterate LaunchFunctions
        self.launch_functions = LaunchFunctions(BatcherMainWindow,self)

        # Popup window
        self.snippet_text_edit = QtWidgets.QTextEdit()
        run_snap = QtWidgets.QPushButton("Launch SnapBatch")
        run_snap.clicked.connect(self.sub_launch_batch_snap)
        main_layout.addWidget(QtWidgets.QLabel("New process"), 0)
        main_layout.addWidget(self.snippet_text_edit)
        main_layout.addWidget(run_snap)
        main_layout.addSpacing(5)

        self.tools_widget = QtWidgets.QWidget()
        self.tools_widget.setLayout(main_layout)
        self.setCentralWidget(self.tools_widget)

    def sub_launch_batch_snap(self):
        """
        Execute launch_batch_snap with the added snippets
        """
        self.add_process = self.snippet_text_edit.toPlainText()
        self.launch_functions.launch_batch_snap(self.snap_shot_lst, self.selected_task, self.selected_vup, self.add_scattering, self.add_process)


class LaunchFunctions:
    """
    Batcher functions
    """

    def __init__(self, main_window, popup_window):
        self.main_window = main_window
        self.popup_window = popup_window


    def get_episode_info(self,episode_nb):
        """
        Get episode sequences list and shots list
        Edit the window according to episode information
        :param episode_nb : string() : episode number
        """
        self.main_window.shot_tree_widget.clear()
        episode_infos = get_shot_list(episode_nb)
        tree_widget_items_lst = list()
        for sequence, shots in episode_infos.items():
            sequence_item = QtWidgets.QTreeWidgetItem([sequence])
            for shot in shots:
                shot_item = QtWidgets.QTreeWidgetItem(["",shot])
                sequence_item.addChild(shot_item)
            tree_widget_items_lst.append(sequence_item)
        self.main_window.shot_tree_widget.insertTopLevelItems(0,tree_widget_items_lst)

    def update_shot_count(self):
        """
        Update selected shot count in main window
        """
        selection = self.main_window.shot_tree_widget.selectedItems()
        if selection:
            count = len(selection)
        else:
            count = 0
        self.get_selected_items()
        self.main_window.count_line.setText(f"{count}")

    def get_selected_items(self):
        """
        Get selected shots/sequence from main window
        :return: selected_shots : list(string) : list of selected shots
        """
        selected_shots = list()
        selection_lst = self.main_window.shot_tree_widget.selectedItems()
        for item in selection_lst:
            if item.text(1):
                shot_sequence = item.parent().text(0)
                shot_short_name = item.text(1).split("_")[-1]
                shot_long_name = shot_sequence + "_" + shot_short_name
                selected_shots.append(shot_long_name)
            if item.text(0):
                for row in range(0,item.childCount()):
                    child_item = item.child(row)
                    shot_sequence = item.text(0)
                    shot_short_name = child_item.text(1).split("_")[-1]
                    shot_long_name = shot_sequence + "_" + shot_short_name
                    if shot_long_name not in selected_shots:
                        selected_shots.append(shot_long_name)

        return selected_shots

    def sub_check_launch_batch_snap(self):
        """
        Check the main window selected options before launching snap
        If checked add process : show pop-up window
        """
        # Get snap secondary actions
        snap_shot_lst = self.get_selected_items()
        selected_task = self.main_window.task_box.currentText()
        selected_vup = self.main_window.vup_checkbox.isChecked()
        add_scattering = self.main_window.scattering_checkbox.isChecked()
        add_process = self.main_window.add_checkbox.isChecked()
        # Check for python snippets
        if add_process:
            self.popup_window = PopUpWindow(snap_shot_lst, selected_task, selected_vup, add_scattering, add_process)
            self.main_window.dialogs.append(self.popup_window)
            self.popup_window.show()
        else :
            self.launch_batch_snap(snap_shot_lst, selected_task, selected_vup, add_scattering, add_process)

    def launch_batch_snap(self,snap_shot_lst, selected_task, selected_vup, add_scattering, add_process):
        """
        Launch batch snap
        :param snap_shot_lst: list(string) : list of selected shots
        :param selected_task: string() : selected task
        :param selected_vup: boolean() : choose to launch vup
        :param add_scattering: boolean() : choose to enable scattering on grass patch
        :param add_process: boolean() : choose whether to add subprocesses
        """
        if add_process:
            pass
        else:
            add_process = str()
        batch_snap(snap_shot_lst, selected_task, selected_vup, add_scattering, add_process)




# _____________________TEMP_____________________


#_____________________LAUNCHER_____________________
def run_ui():
    BatcherMainWindow.show_ui()

def open_snap_batcher():
    try:
        batcher_window.close()  # pylint: disable=E0601
        batcher_window.deleteLater()
    except:
        pass

    batcher_window = BatcherMainWindow()
    batcher_window.show()
