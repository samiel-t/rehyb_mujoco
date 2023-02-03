'''
Script computing the upper arm scale minimizing the center of rotation offset of the elbows
'''

import os
import numpy as np

from mujoco_py import load_model_from_path, MjSim
from shared_utils.general import gen_models_folder_path, models_folder_path, get_project_root, remove_tmp_files
from xml_generation.utils import save_xml_file
from xml.etree import ElementTree as ET
from shared_utils.xacro import set_xacro_property, parse_xacro_to_xml, register_xacro_namespace


def quaternion_multiply(quaternion1, quaternion0):
    '''
    Source: https://stackoverflow.com/questions/39000758/how-to-multiply-two-quaternions-by-python-or-numpy
    '''
    w0, x0, y0, z0 = quaternion0
    w1, x1, y1, z1 = quaternion1
    return np.array([-x1 * x0 - y1 * y0 - z1 * z0 + w1 * w0,
                     x1 * w0 + y1 * z0 - z1 * y0 + w1 * x0,
                     -x1 * z0 + y1 * w0 + z1 * x0 + w1 * y0,
                     x1 * y0 - y1 * x0 + z1 * w0 + w1 * z0], dtype=np.float64)


if __name__ == "__main__":
    ''' prepare xacro generation'''
    register_xacro_namespace()

    XACRO_REL_PATH = os.path.relpath(os.path.join(
        models_folder_path(), "exo_with_patient", "nesm_with_patient.xacro"))

    ROOT_TO_TMP = "bin/outputs/mc_tmp"
    PATH_TO_TMP = os.path.join(get_project_root(), ROOT_TO_TMP)

    tmp_xacro_filename = "aligned_scale_exo_tmp_.xacro"
    tmp_xml_filename = "aligned_scale_exo_tmp_.xml"
    tmp_xml_path = os.path.join(PATH_TO_TMP, tmp_xml_filename)

    ''' pre compute data '''
    # nesm_abspath = os.path.join(
    #     gen_models_folder_path(), "exo_with_patient",
    #     "nesm_with_patient.xml"
    # )

    # assert os.path.isfile(nesm_abspath)

    # model = load_model_from_path(nesm_abspath)

    # tested scales
    scale_lb, scale_ub = .8488, .88
    scale_array = np.linspace(scale_lb, scale_ub, 10)
    min_score = np.inf

    for scale in scale_array:
        # generate model via xacro
        xacro_root = ET.parse(XACRO_REL_PATH).getroot()

        # the gen xml model is not in the usual location 'bin/models/exo_with_patient'
        # Therefore the 'path_to_root' property has to be adjusted
        set_xacro_property(xacro_root, "path_to_root", "../../..")
        set_xacro_property(xacro_root, 'scale_ua', str(scale))

        save_xml_file(xacro_root, tmp_xacro_filename, PATH_TO_TMP)

        # parse newly generated xacro file into xml (uses xacro.sh)
        parse_xacro_to_xml(tmp_xacro_filename,
                           tmp_xml_filename, ROOT_TO_TMP)

        model = load_model_from_path(tmp_xml_path)
        sim = MjSim(model)
        sim.forward()

        # get indices
        # get human elbow joint index
        elbow_joint_name = "el_x"
        elbow_joint_index = model.joint_name2id(elbow_joint_name)
        # deduce position in local parent body frame
        elbow_joint_lpos = model.jnt_pos[elbow_joint_index]
        # get parent body index
        elbow_body_name = "ulna_r"
        elbow_body_index = model.body_name2id(elbow_body_name)

        # get elbow flexion actuator index
        act_joint_name = "J4"
        act_joint_index = model.joint_name2id(act_joint_name)
        # deduce position in local parent body frame
        act_joint_lpos = model.jnt_pos[act_joint_index]
        # get parent body index
        actjoint_body_name = "Link4"
        actjoint_body_index = model.body_name2id(actjoint_body_name)

        # get actuator index
        actuator_name = "eFE"
        actuator_index = model.actuator_name2id(actuator_name)

        # apply flexion
        sim.data.ctrl[actuator_index] = .3

        n_flexion_steps = 200

        # list of cor offsets = pos_el_x - pos_J4 (dim: n x 3)
        cor_offsets = []
        for _ in range(n_flexion_steps):
            # get cor offset
            act_joint_pos = sim.data.get_body_xpos(
                actjoint_body_name) + act_joint_lpos
            elbow_joint_pos = sim.data.get_body_xpos(
                elbow_body_name) + elbow_joint_lpos
            abs_cor_offset = elbow_joint_pos - act_joint_pos

            # compute quat
            quat_cor_offset = np.concatenate((np.zeros(1), abs_cor_offset))
            quat_actjoint_body = sim.data.get_body_xquat(actjoint_body_name)

            # rotate in local frame
            local_cor_offset = quaternion_multiply(
                quat_actjoint_body, quat_cor_offset)[1:]

            cor_offsets.append(local_cor_offset)

            # step
            sim.step()

        score = np.linalg.norm(np.mean(np.array(cor_offsets), axis=0))
        print(f"Scale: {scale}; score: {score}")

        if score < min_score:
            min_score = score
            min_scale = scale

    remove_tmp_files(PATH_TO_TMP, f"_tmp_.*")

    print(f"Best scale: {min_scale}")
