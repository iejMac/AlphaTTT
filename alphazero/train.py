from model import ZeroTTT
from trainer import Trainer

model_args = {
  "board_len": 10,
  "lr": 1e-4,
  "weight_decay": 3e-4
}

mcts_args = {
  "num_simulations": 600,
  "alpha": 0.25,
  "c_puct": 8,
  "dirichlet_alpha": 0.3
}

db_args = {
  "max_len": 10000,
  "augmentations": ["flip", "rotate"]
}

model = ZeroTTT(brain_path="trained_model_2", opt_path="trained_opt_state_2", args=model_args)

args = {
  "mcts_args": mcts_args,
  "db_args": db_args,
  "board_len": 10
}

trainer = Trainer(model, args)
trainer.generate_game(True)
