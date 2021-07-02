import time
import math
import random
import numpy as np
from copy import deepcopy

from database import prepare_state

np.random.seed(80085)
random.seed(80085)

'''
Tasks:
1. Implement iterative search without Node and Edge classes
2. Try to add a quick way of figuring out if the state is terminal and automatically return -1 or +1 rather than consulting the model (should provide a performance boost but not elegant)
'''

def PUCT_score(child_value, child_prior, parent_visit_count, child_visit_count, c_puct):
  pb_c = child_prior * math.sqrt(parent_visit_count) / (child_visit_count + 1)
  return child_value + c_puct * pb_c

class MCTS():
  def __init__(self, model, root_state, c_puct=4, alpha=0.25):
    self.model = model
    self.root = root_state
    self.alpha = alpha
    self.c_puct = c_puct

    self.Qsa = {} # self.Qsa(s, a) = Q value for (s, a)
    self.Nsa = {} # self.Nsa(s, a) = (s, a) visit count
    self.Ns = {} # self.Ns(s) = s visit count
    self.Ps = {} # self.Ps(s) = list of available actions in s and corresponding raw probabilities

    # self.Es = {} # terminal states, potentially going to do this if not too computationally expensive and dirty

    # Add dirichlet noise to initial root node
    self.add_dirichlet()

  def add_dirichlet(self):
    rs = self.root.tobytes()
    if rs not in self.Ps:
      self.find_leaf(deepcopy(self.root))

    dirichlet = np.random.dirichlet([0.3]*len(self.Ps[rs]))
    for i, (move, prob) in enumerate(self.Ps[rs]):
      self.Ps[rs][i] = (move, (1 - self.alpha) * prob + dirichlet[i] * self.alpha)

  def search(self, num_simulations): # builds the search tree from the root node
    t0 = time.time()
    for i in range(num_simulations):
      self.find_leaf(deepcopy(self.root))
    print(f"Time: {time.time() - t0}")
    return

  def find_leaf(self, state):
    s = state.tobytes()

    if s not in self.Ps: # expand leaf node
      p, v = self.model.predict(prepare_state(state)) 
      availability_mask = (state == 0)
      p *= availability_mask
      if np.sum(p) > 0.0:
        p /= np.sum(p) # re-normalize

      move_probs = []

      for i, row in enumerate(p): 
        for j, prob in enumerate(row):
          if state[i][j] == 0:
            move_probs.append(((i, j), prob))
   
      self.Ps[s] = move_probs
      self.Ns[s] = 1
      return -v

    max_puct = -float('inf')
    max_action = None

    for move, prob in self.Ps[s]:
      (Nc, Qc) = (self.Nsa[(s, move)], self.Qsa[(s, move)]) if (s, move) in self.Nsa else (0, 0.0)
      puct = PUCT_score(Qc, prob, self.Ns[s], Nc, self.c_puct)
      if puct > max_puct:
        max_puct = puct
        max_action = move

    a = max_action
    state[a] = 1
    state *= -1

    v = self.find_leaf(state)

    if (s, a) in self.Nsa:
      self.Nsa[(s, a)] += 1
      self.Qsa[(s, a)] = (self.Nsa[(s, a)] * self.Qsa[(s, a)] + v) / (self.Nsa[(s, a)] + 1)
    else:
      self.Nsa[(s, a)] = 1
      self.Qsa[(s, a)] = v
      
    self.Ns[s] += 1
    return -v

  def get_pi(self, tau=1.0, as_prob=True):
    move_dist = np.zeros((len(self.root), len(self.root)))
    rs = self.root.tobytes()
    for move, _ in self.Ps[rs]:
      move_dist[move] = self.Nsa[(rs, move)] if (rs, move) in self.Nsa else 0
    if as_prob is True:
      move_dist = np.power(move_dist, 1.0/tau)
      if np.sum(move_dist) > 0.0:
        move_dist /= np.sum(move_dist)
    return move_dist

  def select_move(self, tau=1.0, external_move=None):
    if external_move is None:
      probas = self.get_pi(tau)
      selected_move = int(np.random.choice(len(probas.flatten()), 1, p=probas.flatten()))
      selected_move = np.unravel_index(selected_move, probas.shape)
    else:
      selected_move = external_move

    self.root[selected_move] = 1
    self.root *= -1

    # Add dirichlet noise to new root node:
    self.add_dirichlet()

    return selected_move