import torch.nn.functional as F
import torch as T
import torch.nn as nn
import torch.optim as optim
import numpy as np
import os

class DeepQNetwork(nn.Module):
    def __init__(self, n_sats, lr, input_dims, fc1_dims, fc2_dims, n_actions, settings):
        super(DeepQNetwork, self).__init__()
        self.input_dims = input_dims
        self.fc1_dims = fc1_dims
        self.fc2_dims = fc2_dims
        self.n_actions = n_actions
        self.n_sats = n_sats
        self.settings = settings
        self.fc1 = nn.Linear(*self.input_dims, self.fc1_dims)
        self.fc2 = nn.Linear(self.fc1_dims,self.fc2_dims)
        self.fc3 = nn.Linear(self.fc2_dims, self.n_actions)
        self.optimizer = optim.Adam(self.parameters(), lr=lr)
        self.loss = nn.MSELoss()
        self.device = T.device('cuda:0' if T.cuda.is_available() else 'cpu')
        self.to(self.device)
        chkpt_dir = 'tmp/dqn/'
        self.checkpoint_file = os.path.join(chkpt_dir, 'madqn_q_network')

    def forward(self, state):
        norm_tensor_array = []
        for i in range(self.n_sats):
            norm_tensor_array.append(86400*self.settings["time"]["duration"]/self.settings["time"]["step_size"])
            norm_tensor_array.append(self.settings["instrument"]["ffor"]/2)
            norm_tensor_array.append(180)
            norm_tensor_array.append(180)
        norm_tensor_array.append(self.n_sats)

        state = state / T.tensor(norm_tensor_array, dtype=T.float).to(self.device)
        x = F.relu(self.fc1(state))
        x = F.relu(self.fc2(x))
        actions = self.fc3(x)

        return actions
    
    def save_checkpoint(self,flag):
        T.save(self.state_dict(), self.checkpoint_file+flag)

    def load_checkpoint(self,flag):
        self.load_state_dict(T.load(self.checkpoint_file+flag))
    
class Agent:
    def __init__(self, settings, n_sats, gamma, epsilon, lr, input_dims, batch_size, n_actions,
                 max_mem_size=10000, eps_end=0.01, eps_dec=5e-5):
        self.gamma = gamma
        self.epsilon = epsilon
        self.eps_min = eps_end
        self.eps_dec = eps_dec
        self.lr = lr
        self.action_space = [i for i in range(n_actions)]
        self.mem_size = max_mem_size
        self.batch_size = batch_size
        self.mem_cntr = 0
        
        self.Q_eval = DeepQNetwork(n_sats, self.lr, n_actions=n_actions, input_dims=input_dims, fc1_dims=256, fc2_dims=256, settings=settings)
        
        self.state_memory = np.zeros((self.mem_size, *input_dims), dtype=np.float32)
        self.new_state_memory = np.zeros((self.mem_size, *input_dims), dtype=np.float32)

        self.action_memory = np.zeros(self.mem_size, dtype=np.int32)
        self.reward_memory = np.zeros(self.mem_size, dtype=np.float32)
        self.terminal_memory = np.zeros(self.mem_size, dtype=np.bool_)

    def store_transition(self, state, action, reward, state_, done):
        index = self.mem_cntr %self.mem_size
        self.state_memory[index] = state
        self.new_state_memory[index] = state_
        self.action_memory[index] = action
        self.reward_memory[index] = reward
        self.terminal_memory[index] = done

        self.mem_cntr += 1

    def choose_action(self, observation):
        if np.random.random() > self.epsilon:
            state = T.tensor([observation], dtype=T.float).to(self.Q_eval.device)
            actions = self.Q_eval.forward(state)
            action = T.argmax(actions).item()
        else:
            action = np.random.choice(self.action_space)
        
        return action
    
    def learn(self):
        if self.mem_cntr < self.batch_size:
            return
        
        self.Q_eval.optimizer.zero_grad()
        
        max_mem = min(self.mem_cntr, self.mem_size)
        batch = np.random.choice(max_mem, self.batch_size, replace=False)

        batch_index = np.arange(self.batch_size, dtype=np.int32)

        state_batch = T.tensor(self.state_memory[batch]).to(self.Q_eval.device)
        new_state_batch = T.tensor(self.new_state_memory[batch]).to(self.Q_eval.device)
        reward_batch = T.tensor(self.reward_memory[batch]).to(self.Q_eval.device)
        terminal_batch = T.tensor(self.terminal_memory[batch]).to(self.Q_eval.device)
        action_batch = self.action_memory[batch]
        
        q_eval = self.Q_eval.forward(state_batch)[batch_index, action_batch]
        q_next = self.Q_eval.forward(new_state_batch)
        q_next[terminal_batch] = 0.0
        q_target = reward_batch + self.gamma * T.max(q_next, dim=1)[0]

        loss = self.Q_eval.loss(q_target, q_eval).to(self.Q_eval.device)
        loss.backward()
        self.Q_eval.optimizer.step()

        self.epsilon = self.epsilon - self.eps_dec if self.epsilon > self.eps_min \
                        else self.eps_min
        
    def save_models(self,flag=""):
        print('saving models')
        self.Q_eval.save_checkpoint(flag)

    def load_models(self,flag=""):
        print('loading models')
        self.Q_eval.load_checkpoint(flag)
