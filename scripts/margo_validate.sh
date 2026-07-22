#!/usr/bin/env bash
#
# Validate deploy/margo/margo.yaml against the vendored Margo Application
# Description schema (margo.org/v1-alpha1).
#
# Run locally:   ./scripts/margo_validate.sh
# In CI:         the `margo-descriptor` job of .github/workflows/ci.yml
#
# Needs `uv` (uses `uvx linkml`); everything else is vendored under
# deploy/margo/schema/ — no network, no repo dependency added. See that
# directory's PROVENANCE.md for what this does and does not prove.
#
# The upstream control examples are validated FIRST, both polarities. A
# validator that has quietly stopped discriminating would pass our descriptor
# just as happily as a working one, so the invalid examples MUST fail for the
# pass on our own file to carry any information.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
schema="${repo_root}/deploy/margo/schema/application-description.linkml.yaml"
examples="${repo_root}/deploy/margo/schema/examples"
descriptor="${repo_root}/deploy/margo/margo.yaml"

# Pinned so a linkml release cannot change the verdict under us.
LINKML_SPEC="linkml==1.11.1"
CLASS="ApplicationDescription"

validate() { uvx --from "${LINKML_SPEC}" linkml-validate -s "${schema}" -C "${CLASS}" "$1"; }

fail() { printf '\n\033[31mFAIL\033[0m %s\n' "$1" >&2; exit 1; }

echo "── controls: upstream examples that MUST pass ──"
for f in "${examples}"/valid-*.yaml; do
  validate "${f}" >/dev/null || fail "upstream VALID example rejected: $(basename "${f}") — the vendored schema or the validator is broken, not our descriptor"
  echo "  ok  $(basename "${f}")"
done

echo "── controls: upstream examples that MUST fail ──"
for f in "${examples}"/invalid-*.yaml; do
  if validate "${f}" >/dev/null 2>&1; then
    fail "upstream INVALID example accepted: $(basename "${f}") — the validator is not discriminating, so a pass below would prove nothing"
  fi
  echo "  ok  $(basename "${f}") (rejected as expected)"
done

echo "── subject: deploy/margo/margo.yaml ──"
validate "${descriptor}" || fail "deploy/margo/margo.yaml is not valid against margo.org/v1-alpha1"

printf '\n\033[32mPASS\033[0m descriptor is structurally valid against the published Margo schema.\n'
echo 'This is NOT a compliance claim — see deploy/margo/schema/PROVENANCE.md.'
