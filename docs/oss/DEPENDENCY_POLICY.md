# Dependency and image policy

MarketOS keeps the commercial core separate from adopted OSS through adapters,
optional libraries, and independently deployed sidecars. No Git submodule or
copied upstream source is permitted for an OSS candidate in the inventory.

- Every adopted OSS component has an exact reviewed reference in
  `INVENTORY.yml` and `LICENSE_MANIFEST.yml`.
- Optional profiles must use exact Python versions. The typed-agent profile is
  pinned in `requirements-oss-agents.txt`; browser automation is pinned by the
  worker Docker build argument.
- Container images must use a version tag or digest. Postiz is digest-pinned;
  image references are checked by `validate_container_pins.py`.
- Base runtime requirements remain compatibility ranges while the repository
  completes a full lockfile migration. Release artifacts must include the
  generated SBOM, which records the resolved versions actually installed.
- CI runs `pip-audit` against both the base and optional agent requirements.
  A known vulnerability blocks delivery until remediated or formally handled
  outside this repository's source policy.
- Dependabot checks Python dependencies, Docker images, and GitHub Actions
  weekly. Review updates against the OSS inventory before merging, especially
  sidecar image and restricted-license changes.
- Releases must retain `THIRD_PARTY_NOTICES.md`, the license manifest, and the
  generated SBOM. New or changed candidates require review of direct and
  transitive licenses, security posture, ownership, rollback, and attribution.
