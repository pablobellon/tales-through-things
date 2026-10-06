#!/bin/bash
# Publish the current code to the server and restart T3.
# Never copies .env, certs/, the archive or runs: those stay where they are.
#
# The server is the SSH host "t3-vps", defined privately in ~/.ssh/config:
#   Host t3-vps
#     HostName <server address>
#     User <user>
# usage: tools/deploy.sh   (or T3_DEPLOY_HOST=other-host tools/deploy.sh)
set -euo pipefail
HOST=${T3_DEPLOY_HOST:-t3-vps}
cd "$(dirname "$0")/.."

rsync -a --delete \
  --exclude '.venv/' --exclude '.env' --exclude 'api.env' --exclude 'certs/' \
  --exclude 'archive/' --exclude 'runs/' --exclude '__pycache__/' --exclude '.DS_Store' \
  --exclude '_*.html' \
  --exclude '.git/' --exclude '.gitignore' \
  ./ "$HOST:t3/app/"

ssh "$HOST" 'cd ~/t3/app && ~/.local/bin/uv pip install -q --python .venv/bin/python -r requirements.txt \
  && sudo systemctl restart t3 && sleep 3 && systemctl is-active t3'
echo "Deployed to $HOST"
