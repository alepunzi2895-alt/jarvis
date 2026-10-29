#!/usr/bin/env bash
# Pull sicuro dei progetti in ~/Downloads, uguale su Windows (Git Bash) e Mac.
# Uso: bash tools/pull_progetti.sh            -> tutti i progetti elencati
#      bash tools/pull_progetti.sh aura       -> solo quelli passati (nomi sotto)
# Regole: solo `pull --ff-only origin main`; salta repo assenti, con modifiche
# locali non committate o con ramo diverso da main. Non tocca mai il working tree
# con reset/stash/checkout.

set -u
BASE="$HOME/Downloads"

# nome-breve:cartella (sotto ~/Downloads)
PROGETTI=(
  "aura:auraibiza"
  "conciergeflow:ConciergeFlow"
  "whitesoul:whitesoulibiza"
  "vmscout:VMScout"
  "property-scout:property_scout"
  "trading:tradeflow-ai"
  "tradepilot-ai:tradepilot-ai"
  "eyra:EYRA"
  "ivgagent:IVGAgent"
  "alessandropunzi-systems:alessandropunzi_systems"
)

filtro="${*:-}"
ok=0; skip=0

for riga in "${PROGETTI[@]}"; do
  nome="${riga%%:*}"
  dir="$BASE/${riga#*:}"
  if [ -n "$filtro" ] && ! echo " $filtro " | grep -q " $nome "; then continue; fi

  if [ ! -d "$dir/.git" ]; then
    echo "[$nome] assente: $dir"; skip=$((skip+1)); continue
  fi
  branch=$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null)
  if [ "$branch" != "main" ]; then
    echo "[$nome] ramo '$branch' (non main): pull saltato"; skip=$((skip+1)); continue
  fi
  if [ -n "$(git -C "$dir" status --porcelain --untracked-files=no)" ]; then
    echo "[$nome] modifiche locali non committate: pull saltato (vedi git -C \"$dir\" status)"
    skip=$((skip+1)); continue
  fi
  if ! git -C "$dir" fetch origin main >/dev/null 2>&1; then
    echo "[$nome] fetch fallito (rete o accesso)"; skip=$((skip+1)); continue
  fi
  if git -C "$dir" pull --ff-only origin main >/dev/null 2>&1; then
    head=$(git -C "$dir" log -1 --format='%h %s')
    echo "[$nome] ok -> $head"; ok=$((ok+1))
  else
    echo "[$nome] pull --ff-only non possibile (storia divergente): verifica a mano"
    skip=$((skip+1))
  fi
done

echo "--- ok: $ok, saltati: $skip"
