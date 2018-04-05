import torch.nn as nn
from torch.nn.init import xavier_uniform
import surreal.utils as U
import torch.nn.functional as F
import numpy as np

from .model_builders import *
from .z_filter import ZFilter

class DiagGauss(object):
    '''
        Class that encapsulates Diagonal Gaussian Probability distribution
        Attributes:
            d: action dimension
        Member Functions:
            loglikelihood
            likelihood
            kl
            entropy
            sample
            maxprob
    '''
    def __init__(self, action_dim):
        self.d = action_dim

    def loglikelihood(self, a, prob):
        '''
            Method computes loglikelihood of action (a) given probability (prob)
        '''
        mean0 = prob[:, :self.d]
        std0 = prob[:, self.d:]
        return - 0.5 * (((a - mean0) / std0).pow(2)).sum(dim=1, keepdim=True) - 0.5 * np.log(
            2.0 * np.pi) * self.d - std0.log().sum(dim=1, keepdim=True)

    def likelihood(self, a, prob):
        '''
            Method computes likelihood of action (a) given probability (prob)
        '''
        return torch.clamp(self.loglikelihood(a, prob).exp(), min=1e-5)

    def kl(self, prob0, prob1):
        '''
            Method computes KL Divergence of between two probability distributions
            Note: this is D_KL(prob0 || prob1), not D_KL(prob1 || prob0)
        '''
        mean0 = prob0[:, :self.d]
        std0 = prob0[:, self.d:]
        mean1 = prob1[:, :self.d]
        std1 = prob1[:, self.d:]
        return ((std1 / std0).log()).sum(dim=1) + (
            (std0.pow(2) + (mean0 - mean1).pow(2)) / (2.0 * std1.pow(2))).sum(dim=1) - 0.5 * self.d

    def entropy(self, prob):
        '''
            Method computes entropy of a given probability (prob)
        '''
        std_nd = prob[:, self.d:]
        return 0.5 * std_nd.log().sum(dim=1) + .5 * np.log(2 * np.pi * np.e) * self.d

    def sample(self, prob):
        '''
            Method samples actions from probability distribution
        '''
        mean_nd = prob[:, :self.d]
        std_nd = prob[:, self.d:]
        return np.random.randn(prob.shape[0], self.d) * std_nd + mean_nd

    def maxprob(self, prob):
        '''
            Method deterministically sample actions of maximum likelihood
        '''
        return prob[:, :self.d]


class PPOModel(U.Module):
    '''
        PPO Model class that wraps aroud the actor and critic networks
        Attributes:
            actor: Actor network, see surreal.model.model_builders.builders
            critic: Critic network, see surreal.model.model_builders.builders
            z_filter: observation z_filter. see surreal.model.z_filter
        Member functions:
            update_target_param: updates kept parameters to that of another model
            update_target_param: updates kept z_filter to that of another model
            forward_actor: forward pass actor to generate policy with option
                to use z-filter
            forward_actor: forward pass critic to generate policy with option
                to use z-filter
            z_update: updates Z_filter running obs mean and variance
    '''
    def __init__(self,
                 init_log_sig,
                 obs_dim,
                 action_dim,
                 use_z_filter,
                 use_cuda):
        super(PPOModel, self).__init__()

        # hyperparameters
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.use_z_filter = use_z_filter
        self.init_log_sig = init_log_sig

        self.actor = PPO_ActorNetwork(self.obs_dim, self.action_dim, self.init_log_sig)
        self.critic = PPO_CriticNetwork(self.obs_dim)
        if self.use_z_filter:
            self.z_filter = ZFilter(obs_dim, use_cuda=use_cuda)

    def update_target_params(self, net):
        '''
            updates kept parameters to that of another model
            Args:
                net: another PPO_Model instance
        '''
        self.actor.load_state_dict(net.actor.state_dict())
        self.critic.load_state_dict(net.critic.state_dict())

    def update_target_z_filter(self, net):
        '''
            updates kept z-filter to that of another model
            Args:
                net: another PPO_Model instance
        '''
        if self.use_z_filter:
            self.z_filter.load_state_dict(net.z_filter.state_dict())

    def forward_actor(self, obs):
        '''
            forward pass actor to generate policy with option to use z-filter
            Args:
                obs -- batch of observations
            Returns:
                The output of actor network
        '''
        shape = obs.size()
        assert len(shape) == 2 and shape[1] == self.obs_dim
        if self.use_z_filter:
            obs = self.z_filter.forward(obs)

        return self.actor(obs)

    def forward_critic(self, obs):
        '''
            forward pass critic to generate policy with option to use z-filter
            Args: 
                obs -- batch of observations
            Returns:
                output of critic network
        '''
        shape = obs.size()
        assert len(shape) == 2 and shape[1] == self.obs_dim
        if self.use_z_filter:
            obs = self.z_filter.forward(obs)

        return self.critic(obs)

    def z_update(self, obs):
        '''
            updates Z_filter running obs mean and variance
            Args: obs -- batch of observations
        '''
        if self.use_z_filter:
            self.z_filter.z_update(obs)
        else:
            raise ValueError('Z_update called when network is set to not use z_filter')