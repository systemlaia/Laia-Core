#!/usr/bin/env bash

set -e

NAS_HOST="192.168.1.144"
NAS_SHARE="Public"
NAS_USER="iv"

MOUNT_POINT="$HOME/NAS/Public"

echo "== LAIA NAS REMOUNT =="

mkdir -p "$HOME/NAS"

if mount | grep -q "$MOUNT_POINT"; then
    echo "NAS already mounted at $MOUNT_POINT"
    exit 0
fi

mkdir -p "$MOUNT_POINT"

echo "Mounting //$NAS_USER@$NAS_HOST/$NAS_SHARE"

mount_smbfs "//$NAS_USER@$NAS_HOST/$NAS_SHARE" "$MOUNT_POINT"

echo
echo "Mount complete."

mount | grep smbfs
