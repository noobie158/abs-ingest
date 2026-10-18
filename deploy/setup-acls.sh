#!/usr/bin/env bash
# One-time permission setup for the audiobook folders (replaces running set_acls.sh by hand).
#
#   sudo ./setup-acls.sh                 # uses /srv/audiobooks (below)
#   sudo ./setup-acls.sh /dir1 /dir2     # or any folders you name
#
# For every folder it: sets owner abs-ingest + group audiobookshelf, turns on setgid (new items keep
# the group), and adds ACLs *and default ACLs* so every NEW file/folder automatically gets
# read+write for both abs-ingest and the audiobookshelf group - no per-file fixing.
#
# Override names with:  OWNER=someone GROUP=othergroup sudo -E ./setup-acls.sh
set -euo pipefail

OWNER="${OWNER:-abs-ingest}"
GROUP="${GROUP:-audiobookshelf}"

DEFAULT_DIRS=(
    /srv/audiobooks/inbox
    /srv/audiobooks/review
    /srv/audiobooks/library
    /srv/audiobooks/processing
    /srv/audiobooks/failed
)
if [[ $# -gt 0 ]]; then DIRS=("$@"); else DIRS=("${DEFAULT_DIRS[@]}"); fi

BLUE='\033[0;34m'; GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'

[[ $EUID -eq 0 ]] || { echo -e "${RED}Run as root (sudo).${NC}" >&2; exit 1; }
command -v setfacl >/dev/null || { echo -e "${RED}setfacl not found: sudo apt install acl${NC}" >&2; exit 1; }
getent group "$GROUP" >/dev/null || { echo -e "${RED}group '$GROUP' does not exist${NC}" >&2; exit 1; }
id "$OWNER" >/dev/null 2>&1 || { echo -e "${RED}user '$OWNER' does not exist${NC}" >&2; exit 1; }

# Review and library storage must already exist; never create them on the wrong filesystem.
for d in /srv/audiobooks/review /srv/audiobooks/library; do
    for given in "${DIRS[@]}"; do
        if [[ "$given" == "$d" && ! -d "$d" ]]; then
            echo -e "${RED}$d does not exist - is the target filesystem mounted?${NC}" >&2
            exit 1
        fi
    done
done

for given in "${DIRS[@]}"; do
    [[ -e "$given" ]] || mkdir -p "$given"
    dir="$(readlink -f "$given")"          # follow links such as Desktop/Linktoaudiobook-staging
    echo -e "${BLUE}== $given${NC}$([[ "$dir" != "$given" ]] && echo "  ->  $dir")"

    chown -R "$OWNER:$GROUP" "$dir"
    find "$dir" -type d -exec chmod 2775 {} +
    find "$dir" -type f -exec chmod 664 {} +
    setfacl -R -m "u:$OWNER:rwX,g:$GROUP:rwX" "$dir"
    find "$dir" -type d -exec setfacl -d -m "u:$OWNER:rwX,g:$GROUP:rwX" {} +
    echo -e "${GREEN}   ok${NC}"
done

if id -nG "$OWNER" | tr ' ' '\n' | grep -qx "$GROUP"; then
    echo "$OWNER is already in group $GROUP"
else
    usermod -aG "$GROUP" "$OWNER"
    echo "added $OWNER to $GROUP - log out and back in (or restart the service) for this to apply"
fi

mkdir -p /var/log/abs-ingest
chown "$OWNER:$GROUP" /var/log/abs-ingest

echo -e "\n${BLUE}Done.${NC} Check with:  getfacl /srv/audiobooks/library"
echo "Samba: files written by the PC must end up readable by $OWNER; the default ACLs above handle that."
