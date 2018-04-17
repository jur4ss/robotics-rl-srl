import argparse
import json
import os
from datetime import datetime

import yaml
from baselines.common.vec_env.subproc_vec_env import SubprocVecEnv
from baselines.common.vec_env.vec_frame_stack import VecFrameStack

import environments.kuka_button_gym_env as kuka_env
from environments.utils import makeEnv
from rl_baselines.deepq import CustomDummyVecEnv, WrapFrameStack
from rl_baselines.utils import CustomVecNormalize
from srl_priors.utils import printGreen, printYellow


def parseArguments(supported_models, log_dir="/tmp/gym/test/"):
    """
    :param supported_models: ([str])
    :param log_dir: (str) Log dir for testing the agent
    :return: (Arguments, dict, str, str, str, SubprocVecEnv)
    """
    parser = argparse.ArgumentParser(description="Load trained RL model")
    parser.add_argument('--env', help='environment ID', type=str, default='KukaButtonGymEnv-v0')
    parser.add_argument('--seed', type=int, default=0, help='random seed (default: 0)')
    parser.add_argument('--num-cpu', help='Number of processes', type=int, default=1)
    parser.add_argument('--log-dir', help='folder with the saved agent model', type=str, required=True)
    parser.add_argument('--num-timesteps', type=int, default=int(1e4))
    parser.add_argument('--render', action='store_true', default=False,
                        help='Render the environment (show the GUI)')
    parser.add_argument('--shape-reward', action='store_true', default=False,
                        help='Shape the reward (reward = - distance) instead of a sparse reward')
    load_args = parser.parse_args()
    # load_args.cuda = not load_args.no_cuda and th.cuda.is_available()

    with open('config/srl_models.yaml', 'rb') as f:
        srl_models = yaml.load(f)

    for algo in supported_models + ['not_supported']:
        if algo in load_args.log_dir:
            break
    if algo == "not_supported":
        raise ValueError("RL algo not supported for replay")
    printGreen("\n" + algo + "\n")

    load_path = "{}/{}_model.pkl".format(load_args.log_dir, algo)

    env_globals = json.load(open(load_args.log_dir + "kuka_env_globals.json", 'r'))
    train_args = json.load(open(load_args.log_dir + "args.json", 'r'))

    kuka_env.FORCE_RENDER = load_args.render
    kuka_env.ACTION_REPEAT = env_globals['ACTION_REPEAT']
    # Reward sparse or shaped
    kuka_env.SHAPE_REWARD = load_args.shape_reward

    kuka_env.ACTION_JOINTS = train_args["action_joints"]
    kuka_env.IS_DISCRETE = not train_args["continuous_actions"]
    kuka_env.BUTTON_RANDOM = train_args.get('relative', False)
    # Allow up action
    # kuka_env.FORCE_DOWN = False

    if train_args["srl_model"] != "":
        train_args["policy"] = "mlp"
        path = srl_models.get(train_args["srl_model"])

        if train_args["srl_model"] == "ground_truth":
            kuka_env.USE_GROUND_TRUTH = True
        elif train_args["srl_model"] == "joints":
            kuka_env.USE_JOINTS = True
        elif train_args["srl_model"] == "joints_position":
            kuka_env.USE_GROUND_TRUTH = True
            kuka_env.USE_JOINTS = True
        elif path is not None:
            kuka_env.USE_SRL = True
            kuka_env.SRL_MODEL_PATH = srl_models['log_folder'] + path
        else:
            raise ValueError("Unsupported value for srl-model: {}".format(train_args["srl_model"]))

    # Log dir for testing the agent
    log_dir += "{}/{}/".format(algo, datetime.now().strftime("%y-%m-%d_%Hh%M_%S"))
    os.makedirs(log_dir, exist_ok=True)

    if algo not in ["deepq", "ddpg"]:
        envs = SubprocVecEnv([makeEnv(train_args['env'], load_args.seed, i, log_dir)
                              for i in range(load_args.num_cpu)])
        envs = VecFrameStack(envs, train_args['num_stack'])
    else:
        if load_args.num_cpu > 1:
            printYellow(algo + " does not support multiprocessing, setting num-cpu=1")
        envs = CustomDummyVecEnv([makeEnv(train_args['env'], load_args.seed, 0, log_dir)])
        # Normalize only raw pixels
        normalize = train_args['srl_model'] == ""
        envs = WrapFrameStack(envs, train_args['num_stack'], normalize=normalize)

    if train_args["srl_model"] != "":
        envs = CustomVecNormalize(envs, training=False)
        # Temp fix for experiments where no running average were saved
        try:
            printGreen("Loading saved running average")
            envs.loadRunningAverage(load_args.log_dir)
        except FileNotFoundError:
            envs.training = True
            printYellow("Running Average files not found for CustomVecNormalize, switching to training mode")

    return load_args, train_args, load_path, log_dir, algo, envs
