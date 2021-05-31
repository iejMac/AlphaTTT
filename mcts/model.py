import os
import numpy as np
from collections import deque

import torch
from torch import nn
from torch.nn import functional as F
from torch.optim import AdamW

from mcts import MCTS
from environment import split_state
from environment import Environment

torch.manual_seed(80085)
np.random.seed(80085)

def softXEnt (inp, target): # temporary
    logprobs = F.log_softmax (inp, dim = 1)
    return  -(target * logprobs).sum() / inp.shape[0]

def append_state(states, labels, state, label):
  # Augmentation
  for i in range(2):
    for j in range(4):
      states.append(np.rot90(state, j))
      labels.append(np.rot90(label, j))
    
    state = state.T
    label = label.T
  
  state = state.T
  label = label.T
  return

class PolicyHead(nn.Module):
  def __init__(self, board_shape, use_bias):
    super().__init__()

    self.board_shape = board_shape

    self.pol_conv1 = nn.Conv2d(48, 32, padding=(2,2), kernel_size=5, stride=1, bias=use_bias)
    self.pol_conv2 = nn.Conv2d(32, 12, padding=(2,2), kernel_size=5, stride=1, bias=use_bias)
    self.pol_conv3 = nn.Conv2d(12, 1, padding=(2,2), kernel_size=5, stride=1, bias=use_bias)

  def forward(self, x):
    p = self.pol_conv1(x)
    p = F.relu(p)
    p = self.pol_conv2(p)
    p = F.relu(p)
    p = self.pol_conv3(p)

    p = p.view(-1, self.board_shape[1]*self.board_shape[2])
    p = F.softmax(p, dim=1)
    p = p.view(-1, self.board_shape[1], self.board_shape[2])
    return p

class ValueHead(nn.Module):
  def __init__(self, use_bias):
    super().__init__()
    self.val_conv1 = nn.Conv2d(48, 24, kernel_size=5, stride=1, bias=use_bias)
    self.val_conv2 = nn.Conv2d(24, 4, kernel_size=3, stride=1, bias=use_bias)

    self.val_linear1 = nn.Linear(64, 50)
    self.val_linear2 = nn.Linear(50, 1)

    self.flatten = nn.Flatten()

  def forward(self, x):
    v = self.val_conv1(x)
    v = F.relu(v)
    v = self.val_conv2(v)
    v = F.relu(v)

    v = self.flatten(v)
    v = self.val_linear1(v)
    v = F.relu(v)
    v = self.val_linear2(v)
    v = torch.tanh(v)
    return v

class Brain(nn.Module):
  def __init__(self, input_shape=(2, 30, 30)):
    super().__init__()

    self.input_shape = input_shape

    use_bias = True
    self.conv1 = nn.Conv2d(input_shape[0], 64, padding=(2,2), kernel_size=5, stride=1, bias=use_bias)
    self.conv2 = nn.Conv2d(64, 96, padding=(2,2), kernel_size=5, stride=1, bias=use_bias)
    self.conv3 = nn.Conv2d(96, 96, padding=(2,2), kernel_size=5, stride=1, bias=use_bias)
    self.conv4 = nn.Conv2d(96, 48, padding=(2,2), kernel_size=5, stride=1, bias=use_bias)

    self.policy_head = PolicyHead(input_shape, use_bias)
    self.value_head = ValueHead(use_bias)

  def forward(self, x):
    # Core:
    x = self.conv1(x)
    x = F.relu(x)
    x = self.conv2(x)
    x = F.relu(x)
    x = self.conv3(x)
    x = F.relu(x)
    x = self.conv4(x)
    x = F.relu(x)

    p, v = self.policy_head(x), self.value_head(x)

    return p, v

class ZeroTTT():
  def __init__(self, brain_path=None, opt_path=None, board_len=10, lr=3e-4, weight_decay=0.0):
    self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    self.brain = Brain(input_shape=(2, board_len, board_len)).to(self.device)
    self.board_len = board_len

    self.optimizer = AdamW(self.brain.parameters(), lr=lr, weight_decay=weight_decay)
    self.value_loss = nn.MSELoss()
    self.policy_loss = nn.CrossEntropyLoss()

    if brain_path is not None:
      self.load_brain(brain_path, opt_path)

  def get_parameter_count(self):
    return sum(p.numel() for p in self.brain.parameters() if p.requires_grad)

  def save_brain(self, model_name, opt_state_name):
    print("Saving brain...")
    torch.save(self.brain.state_dict(), os.path.join('models', model_name))
    if opt_state_name is not None:
        torch.save(self.optimizer.state_dict(), os.path.join('models', opt_state_name))

  def load_brain(self, model_name, opt_state_name):
    print("Loading brain...")
    self.brain.load_state_dict(torch.load(os.path.join('models', model_name), map_location=self.device))
    if opt_state_name is not None:
        self.optimizer.load_state_dict(torch.load(os.path.join('models', opt_state_name), map_location=self.device))
    return

  def predict(self, x):

    if len(x.shape) < 4:
      x = np.expand_dims(x, axis=0)

    x = torch.from_numpy(x).float().to(self.device)

    policy, value = self.brain(x)
    return policy, value

  def self_play(self, n_games=1, num_simulations=100, training_epochs=1, positions_per_learn=100, min_positions_learn=100, batch_size=20 ,render=10):
    
    # Put model in training mode:
    self.brain.train()
    
    states = deque([], maxlen=min_positions_learn)
    policy_labels = deque([], maxlen=min_positions_learn)
    value_labels = deque([], maxlen=min_positions_learn)
    val_chunk = []

    positions_to_next_learn = positions_per_learn

    env = Environment(board_len=self.board_len)

    for game_nr in range(n_games):
      
      mcts = MCTS(self, env.board, num_simulations=num_simulations, alpha=0.25)
      tau = 1.0

      print(f"Game {game_nr+1}...")

      while env.game_over() == 10:

        if len(env.move_hist) > 30: # after 30 moves no randomness
          tau = 0.01

        if np.any(env.board == 0) is False: # tie
          break

        mcts.search()
       
        if env.turn == env.x_token:
          append_state(states, policy_labels, env.board, mcts.get_pi())
        elif env.turn == env.o_token: # swap persepctive so O tokens are positive and X tokens are negative
          append_state(states, policy_labels, (-1)*env.board, mcts.get_pi())

        val_chunk += [env.turn]*8 # accounting for augmentation

        move = mcts.select_move(tau=tau)
        env.step(move)

        if (game_nr+1) % render == 0:
          env.render()

      print(f"Player with token: {env.game_over()} won the game in {len(env.move_hist)} moves")

      if env.game_over() == env.x_token: # pass because the turns correctly specify the return from the proper perspectives
        pass
      elif env.game_over() == env.o_token:
        val_chunk = [lab * (-1.0) for lab in val_chunk] # invert the turns because that will represent -1 return for x turns and 1 for o turns
      else: # tie
        val_chunk = [0 for lab in val_chunk]

      value_labels += val_chunk
      positions_to_next_learn -= len(val_chunk)
      val_chunk = []


      if len(states) >= min_positions_learn and positions_to_next_learn <= 0: # learn

        print(f"Training on {len(states)} positions...")

        train_states = [split_state(state) for state in states]

        train_states = np.array(train_states)
        train_policy_labels = np.array(policy_labels)
        train_value_labels = np.array(value_labels)

        p = np.random.permutation(len(states))

        train_states = train_states[p]
        train_policy_labels = train_policy_labels[p]
        train_value_labels = train_value_labels[p]

        batch_count = int(len(train_states)/batch_size)
        if len(train_states) / batch_size > batch_count:
          batch_count += 1

        for e in range(training_epochs):
          for j in range(batch_count):

            self.optimizer.zero_grad()

            batch_st = train_states[j * batch_size: min((j+1) * batch_size, len(train_states))]
            batch_pl = train_policy_labels[j * batch_size: min((j+1) * batch_size, len(train_policy_labels))]
            batch_vl = train_value_labels[j * batch_size: min((j+1) * batch_size, len(train_value_labels))]

            batch_pl = torch.from_numpy(batch_pl).to(self.device)
            batch_vl = torch.from_numpy(batch_vl).float().to(self.device)
            prob, val = self.predict(batch_st)
            val = val.flatten()
    
            prob = torch.flatten(prob, 1, 2)
            batch_pl = torch.flatten(batch_pl, 1, 2)
    
            p_loss = softXEnt(prob, batch_pl)
            v_loss = self.value_loss(val, batch_vl)
    
            loss = p_loss + v_loss
            loss.backward()
    
            self.optimizer.step()
  
        # Save after training step
        self.save_brain('best_model', 'best_opt_state')
        positions_to_next_learn = positions_per_learn

      env.reset()
