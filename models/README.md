# models/

Fitted scikit-learn pipelines saved by ML Studio (`<comparison_id>_<family>_<feature_set>.joblib`).

* Files are created only by `POST /api/ml/train` on this computer. Their SHA-256 is stored in the `ml_runs`
  table and checked before every load; a file whose hash does not match is refused.
* joblib/pickle files can execute code when loaded. Never copy model files from other people or the
  internet into this folder.
* The folder is git-ignored. Deleting a file here makes predictions with that run impossible (retrain).
* No pretrained or downloaded models are shipped with WETCOR AI.
