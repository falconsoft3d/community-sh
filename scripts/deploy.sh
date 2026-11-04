#!/usr/bin/env bash
# Deploy the latest code of a branch on the server (run as root, from GitHub Actions or by hand):
#
#     sudo bash scripts/deploy.sh [branch] [install dir]        # defaults: main /opt/community-sh
#
# 1. Waits (up to 15 min) for running tasks: rebuilding the workers would cut a deploy,
#    backup or demo in half. Then dumps the panel's database to backups/panel-db/ (the last
#    15 are kept): if the dump fails, nothing is deployed. Nothing else is touched: the
#    instances, their databases and filestores, .env, backups/, instances/ and media/ are
#    not in git, and docker compose keeps its volumes.
# 2. Keeps Traefik's certificate store (letsencrypt/acme.json) out of git's way: losing it
#    would request every certificate again (Let's Encrypt allows 50 a week).
# 3. Moves the code to origin/<branch>, rebuilds the panel's images and restarts what changed.
#    The Odoo instances and user containers are not part of docker compose: they keep running.
# 4. Waits for the panel to answer; if it doesn't, goes back to the previous version.
set -euo pipefail

BRANCH="${1:-main}"
DIR="${2:-/opt/community-sh}"
cd "$DIR"

log() { echo "[deploy $(date '+%H:%M:%S')] $*"; }

# One deploy at a time
exec 9>"/tmp/community-sh-deploy.lock"
if ! flock -w 600 9; then
    log "Another deploy is still running"; exit 1
fi

running_tasks() {
    docker compose exec -T app python manage.py shell -c \
        "from orchestrator.task_models import Task; print(Task.objects.filter(status='running').exclude(kind='ai_chat').count())" \
        2>/dev/null | tail -1 | tr -dc '0-9'
}

for _ in $(seq 1 45); do
    count="$(running_tasks || true)"
    if [ -z "$count" ] || [ "$count" = "0" ]; then break; fi
    log "Waiting for $count running task(s) to finish..."
    sleep 20
done

# A copy of the panel's database before touching anything
DUMPS="backups/panel-db"
mkdir -p "$DUMPS"
STAMP="$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD)"
if grep -q '^DATABASE_URL=postgres' .env 2>/dev/null; then
    # A failed or empty dump stops here: nothing is deployed without a copy
    if ! docker compose exec -T db pg_dump -U postgres --no-owner community_sh | gzip > "$DUMPS/panel-$STAMP.sql.gz" \
            || [ "$(gzip -dc "$DUMPS/panel-$STAMP.sql.gz" | head -c 4096 | wc -c)" -lt 100 ]; then
        log "Could not back up the panel database: nothing deployed"; rm -f "$DUMPS/panel-$STAMP.sql.gz"; exit 1
    fi
    chmod 600 "$DUMPS/panel-$STAMP.sql.gz"
elif [ -f db.sqlite3 ]; then
    cp -p db.sqlite3 "$DUMPS/panel-$STAMP.sqlite3"
fi
log "Panel database saved in $DUMPS ($(ls -1 "$DUMPS" | wc -l | tr -d ' ') copies)"
ls -1t "$DUMPS"/panel-* 2>/dev/null | tail -n +16 | xargs -r rm -f

ACME="letsencrypt/acme.json"
ACME_BACKUP="letsencrypt/acme.json.deploy-backup"
if [ -s "$ACME" ]; then
    cp -p "$ACME" "$ACME_BACKUP"
fi

# acme.json is often marked skip-worktree / assume-unchanged on servers (so git ignores what Traefik
# writes): git then refuses to move to a version that no longer tracks it. It has its own copy above.
if git ls-files --error-unmatch "$ACME" >/dev/null 2>&1; then
    # Two calls: given together, git keeps one of the flags
    git update-index --no-skip-worktree -- "$ACME"
    git update-index --no-assume-unchanged -- "$ACME"
fi
FLAGGED="$(git ls-files -v | awk '/^([a-z]|S) /{ $1=""; sub(/^ /, ""); print }')"
if [ -n "$FLAGGED" ]; then
    log "Files marked skip-worktree/assume-unchanged on this server (left as they are): $(echo "$FLAGGED" | tr '\n' ' ')"
fi

PREVIOUS="$(git rev-parse HEAD)"
git fetch --quiet origin "$BRANCH"
TARGET="$(git rev-parse "origin/$BRANCH")"
# Edits made by hand on the server to tracked files are kept in a patch, never silently lost
# (acme.json holds private keys and has its own copy: never in the patch)
if ! git diff --quiet HEAD -- . ':(exclude)letsencrypt/acme.json'; then
    PATCH="$DUMPS/local-changes-$(date +%Y%m%d-%H%M%S).patch"
    git diff HEAD -- . ':(exclude)letsencrypt/acme.json' > "$PATCH"
    chmod 600 "$PATCH"
    log "Tracked files had local changes: saved to $PATCH"
fi
git reset --quiet --hard
git checkout --quiet --force -B "$BRANCH" "$TARGET"
log "Code: ${PREVIOUS:0:7} -> ${TARGET:0:7} ($BRANCH)"

restore_acme() {
    if [ -s "$ACME_BACKUP" ] && ! cmp -s "$ACME_BACKUP" "$ACME" 2>/dev/null; then
        cp -p "$ACME_BACKUP" "$ACME"
        log "Restored the certificate store"
    fi
    if [ -f "$ACME" ]; then chmod 600 "$ACME"; fi
}
restore_acme

panel_answers() {
    for _ in $(seq 1 36); do
        code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/accounts/login/ || true)"
        if [ "$code" = "200" ]; then return 0; fi
        sleep 5
    done
    return 1
}

build_and_start() {
    docker compose build --quiet
    docker compose up -d
}

log "Building and restarting the panel..."
build_and_start
if panel_answers; then
    log "Panel up at ${TARGET:0:7}"
    docker image prune -f >/dev/null 2>&1 || true
    exit 0
fi

log "The panel did not answer: going back to ${PREVIOUS:0:7}"
docker compose logs --tail=80 app || true
git checkout --quiet --force -B "$BRANCH" "$PREVIOUS"
restore_acme
build_and_start
if panel_answers; then
    log "Rolled back to ${PREVIOUS:0:7}"
else
    log "The previous version does not answer either: check 'docker compose logs app'"
fi
exit 1
