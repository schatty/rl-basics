from datetime import datetime
import time
import numpy as np
import torch
import gym
import os

from utils.logger import Logger
from .utils import ReplayBuffer
from .ddpg import DDPG


# Runs policy for X episodes and returns average reward
# A fixed seed is used for the eval environment
def eval_policy(policy, env_name, seed, eval_episodes=10):
    eval_env = gym.make(env_name)
    eval_env.seed(seed + 100)

    avg_reward = 0.
    for _ in range(eval_episodes):
        state, done = eval_env.reset(), False
        while not done:
            action = policy.select_action(np.array(state))
            state, reward, done, _ = eval_env.step(action)
            avg_reward += reward

    avg_reward /= eval_episodes

    print("---------------------------------------")
    print(f"Evaluation over {eval_episodes} episodes: {avg_reward:.3f}")
    print("---------------------------------------")
    return avg_reward


class Engine(object):
    def __init__(self, config):
        self.config = config

    def train(self):
        config = self.config
        env_name = config["env"]
        seed = config["random_seed"]
        save_dir = config["results_path"]

        state_dim = config["state_dim"]
        action_dim = config["action_dim"]
        min_action = config["action_low"]
        max_action = config["action_high"]
        tau = config["tau"]
        discount = config["discount_rate"]
        load_model = config["load_model"]
        max_timesteps = config["num_steps_train"]
        start_timesteps = config["start_timesteps"]
        batch_size = config["batch_size"]
        eval_freq = config["eval_freq"]
        expl_noise = config["expl_noise"]

        start_time = time.time()
        print("---------------------------------------")
        print(f"Policy: ddpg, Env: {env_name}, Seed: {seed}")
        print("---------------------------------------")

        if not os.path.exists("./results"):
            os.makedirs("./results")

        if not os.path.exists("./models"):
            os.makedirs("./models")

        # Create directory for experiment
        experiment_dir = f"{config['results_path']}/{config['env']}-{config['model']}-{datetime.now():%Y-%m-%d_%H:%M:%S}"
        if not os.path.exists(experiment_dir):
            os.makedirs(f"{experiment_dir}/models")

        logger = Logger(f"{experiment_dir}/agent")
        env = gym.make(env_name)

        # Set seeds
        env.seed(seed)
        torch.manual_seed(seed)
        np.random.seed(seed)

        kwargs = {
            "state_dim": state_dim,
            "action_dim": action_dim,
            "max_action": max_action,
            "discount": discount,
            "tau": tau,
            "log_dir": experiment_dir
        }

        # Initialize policy
        policy = DDPG(**kwargs)

        if load_model is not None:
            policy.load(load_model)

        replay_buffer = ReplayBuffer(state_dim, action_dim)

        # Evaluate untrained policy
        evaluations = [eval_policy(policy, env_name, seed)]

        state, done = env.reset(), False
        episode_reward = 0
        episode_timesteps = 0
        episode_num = 0

        for t in range(max_timesteps):

            episode_timesteps += 1

            # Select action randomly or according to policy

            if t < start_timesteps:
                action = env.action_space.sample()
            else:
                action = (
                        policy.select_action(np.array(state))
                        + np.random.normal(0, max_action * expl_noise, size=action_dim)
                ).clip(-max_action, max_action)

            # Perform action
            next_state, reward, done, _ = env.step(action)
            done_bool = float(done) if episode_timesteps < env._max_episode_steps else 0

            # Store data in replay buffer
            replay_buffer.add(state, action, next_state, reward, done_bool)

            state = next_state
            episode_reward += reward

            # Train agent after collecting sufficient data
            if t >= start_timesteps:
                policy.train(replay_buffer, step=t, batch_size=batch_size)

            if done:
                # +1 to account for 0 indexing. +0 on ep_timesteps since it will increment +1 even if done=True
                print(
                    f"Total T: {t + 1} Episode Num: {episode_num + 1} Episode T: {episode_timesteps} Reward: {episode_reward:.3f}")
                # Reset environment
                state, done = env.reset(), False
                episode_reward = 0
                episode_timesteps = 0
                episode_num += 1

            # Evaluate episode
            if (t + 1) % eval_freq == 0:
                reward = eval_policy(policy, env_name, seed)
                # Save reward
                logger.scalar_summary("agent/eval_reward", reward, t)
                logger.scalar_summary("data_struct/buffer", len(replay_buffer), t)
                # Save model
                policy.save(f"{experiment_dir}/models/policy_{t}")

        total_time = time.time() - start_time
        hh = total_time // 3600
        mm = (total_time % 3600) / 60
        print(f"Evaluation time: {hh} hours {mm:.3} minutes.")