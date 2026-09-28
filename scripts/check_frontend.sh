#!/bin/sh
set -eux

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_root/apps/web"

npm run check:api-contract
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
