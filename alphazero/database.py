import os
import numpy as np
from copy import deepcopy
from collections import deque

def prepare_state(state):
  split = np.zeros((2, len(state), len(state)))
  for i, row in enumerate(state):
    for j, cell in enumerate(row):
      if cell == 1:
        split[0][i][j] = 1
      elif cell == -1:
        split[1][i][j] = 1
  return split

def unprepare_state(prepared_state):
  board_len = len(prepared_state[0])
  state = np.zeros((board_len, board_len))
  for i in range(board_len):
    for j in range(board_len):
      state[i][j] = prepared_state[0][i][j]*1 + prepared_state[1][i][j]*(-1)
  return state

def rotate_augmentation(states, labels):
  aug_states, aug_labels = [], []
  for i in range(len(states)):
    for j in range(4):
      aug_states.append(deepcopy(np.rot90(states[i], j)))
      aug_labels.append(deepcopy(np.rot90(labels[i], j)))
  return aug_states, aug_labels, []
    
def flip_augmentation(states, labels):
  aug_states, aug_labels = [], []
  for i in range(len(states)):
    aug_states += [deepcopy(states[i]), deepcopy(states[i].T)]
    aug_labels += [deepcopy(labels[i]), deepcopy(labels[i].T)]
  return aug_states, aug_labels, []

def swap_perspective_augmentation(states, labels):
  aug_states, aug_labels, val_mask = [], [], []
  for i in range(len(states)):
    aug_states += [deepcopy(states[i]), deepcopy((-1)*states[i])]
    aug_labels += [deepcopy(labels[i]), deepcopy(labels[i])]
    val_mask += [1, -1]
  return aug_states, aug_labels, val_mask

class DataBase:
  def __init__(self, args):
    '''
    args:
      max_len - maximum length of replay buffer in RAM

      augmentations :
        flip - transpose the state and policy (2x)
        rotate - rotate state and policy by 90 degrees (4x)

    '''

    self.max_len = args["max_len"]
    self.augmentations = args["augmentations"]
    self.augmentation_coefficient = 1

    self.states = deque([], maxlen=self.max_len)
    self.policy_labels = deque([], maxlen=self.max_len)
    self.value_labels = deque([], maxlen=self.max_len)
    self.value_mask = []

  def clear(self):
    self.states.clear()
    self.policy_labels.clear()
    self.value_labels.clear()

  def is_full(self):
    return len(self.states) == len(self.policy_labels) == len(self.value_labels) == self.max_len

  def append_policy(self, state, policy_label):
    aug_states = [state]
    aug_policy_labels = [policy_label]

    for aug in self.augmentations:
      aug_states, aug_policy_labels, val_mask = eval(aug + "_augmentation")(aug_states, aug_policy_labels)
      self.value_mask += val_mask

    # Temporary:
    aug_policy_labels = [aug.flatten() for aug in aug_policy_labels]

    self.states += aug_states 
    self.policy_labels += aug_policy_labels
    self.augmentation_coefficient = len(aug_states)

  def append_value(self, winner, game_length):
    val_labs = []
    offset = (-1.0)**(winner == -1.0)
    for i in range(game_length):
      val_labs += [offset * (-1.0)**(i%2 == 1)] * self.augmentation_coefficient

    if len(self.value_mask) == len(val_labs):
      val_labs = [val_labs[i] * self.value_mask[i] for i in range(len(val_labs))]
      self.value_mask = []
    self.value_labels += val_labs

  def save_data(self, path="./replay_buffer"):
    prepared_states = [prepare_state(state) for state in self.states]
    states = np.array(prepared_states)
    pol_labels = np.array(self.policy_labels)
    val_labels = np.array(self.value_labels)

    try:
      largest_index = max([int(name[12:-4]) for name in os.listdir(os.path.join(path, "states"))])
    except ValueError:
      largest_index = -1

    print(f"Saving replay chunk #{largest_index+1} of {len(states)} positions...")
    np.save(os.path.join(path, "states", f"state_chunk_{largest_index+1}"), states)
    np.save(os.path.join(path, "policy_labels", f"policy_chunk_{largest_index+1}"), pol_labels)
    np.save(os.path.join(path, "value_labels", f"value_chunk_{largest_index+1}"), val_labels)

  def load_data(self, path, chunk_num):
    states = np.load(os.path.join(path, "states", f"state_chunk_{chunk_num}.npy"))
    policy_labels = np.load(os.path.join(path, "policy_labels", f"policy_chunk_{chunk_num}.npy"))
    value_labels = np.load(os.path.join(path, "value_labels", f"value_chunk_{chunk_num}.npy"))

    for i, state in enumerate(states):
      self.states.append(unprepare_state(state))
      self.policy_labels.append(policy_labels[i])
      self.value_labels.append(value_labels[i])

  def prepare_batches(self, batch_size, from_memory_paths=None):

    assert(len(self.states) == len(self.policy_labels) == len(self.value_labels))

    # Numpy-ify
    if from_memory_paths is None:
      train_states = np.array([prepare_state(state) for state in self.states])
      train_policy_labels = np.array(self.policy_labels)
      train_value_labels = np.array(self.value_labels)
    else:
      train_states = np.load(os.path.join(from_memory_paths[0]))
      train_policy_labels = np.load(os.path.join(from_memory_paths[1]))
      train_value_labels = np.load(os.path.join(from_memory_paths[2]))

    # Mix up:
    perm = np.random.permutation(len(train_states))
    train_states = train_states[perm]
    train_policy_labels = train_policy_labels[perm]
    train_value_labels = train_value_labels[perm]

    # Cut off incomplete batch
    batch_count = int(len(train_states)/batch_size)
    train_states = train_states[:batch_count*batch_size]
    train_policy_labels = train_policy_labels[:batch_count*batch_size]
    train_value_labels = train_value_labels[:batch_count*batch_size]

    batched_states = np.split(train_states, batch_count)
    batched_policy_labels = np.split(train_policy_labels, batch_count)
    batched_value_labels = np.split(train_value_labels, batch_count)
    
    return batched_states, batched_policy_labels, batched_value_labels
