# M01 artifact inventory

Runtime: `podman version 5.7.0`.
Python: `3.13.14`.

The repository digest is the pinned image index; the platform digest is the selected
linux/amd64 manifest in the local image store. The config digest is the
inspected image ID.
Source-tag licenses are bundled for offline checks. Candidate image paths were checked
in unstarted disposable containers; an empty embedded result means absent at those paths,
not proof that the image contains no license anywhere. Notice review for redistribution
remains an M13 obligation.

| Image | Tag | Index digest | Platform digest | Config digest | License evidence | Embedded license | Embedded notice |
|---|---|---|---|---|---|---|---|
| terminusdb | `v12.0.7` | `sha256:385faf298ad77aaf2d4d6df5e84a4cbe3596d01dab2e3b991af905639ae56388` | `sha256:c5c70435f944a0e91b6846fa6a70c8b6956cb36e5712e60789cd7a45a7084f73` | `sha256:3308827f2e9e76d259fdd1fa04d546330b24d3b912363172f6ced84a4e2b8243` | [Apache-2.0](https://raw.githubusercontent.com/terminusdb/terminusdb/v12.0.7/LICENSE) (`docs/evidence/M01/licenses/terminusdb-LICENSE`, `sha256:d6f15456b303e6be4ac8796b969f3e402f3bddd9699bf302ad08b2a1abc9434f`) | none at checked paths | none at checked paths |
| openfga | `v1.21.0` | `sha256:2113c664a486b5da8d7a2cdab479e0d4e30639c80fd2c000540f645c1dbc1e55` | `sha256:51bece5c31783bfeb150eae0f1c818ae804c50d39e0a311c43ff5357fed6debd` | `sha256:e7bc1233d821701d8f39b1c837fc1c09eb863637ce81b0cf7db3368d72c0d69b` | [Apache-2.0](https://raw.githubusercontent.com/openfga/openfga/v1.21.0/LICENSE) (`docs/evidence/M01/licenses/openfga-LICENSE`, `sha256:1c46d7b2bed94d457d745f28cabeb31f8d6c81dd9035bc5d24039989ee1e1bff`) | none at checked paths | none at checked paths |
| keycloak | `26.7.4` | `sha256:82a77884f3af238beab1e7afd63b5f530e1b5c0590bd7aa60b40a40463e29b2c` | `sha256:3d911baa186f352563854039b95f21a7e2c01c76b527fdc64f24a0885b927bdf` | `sha256:b2f3e1b85071d17a1da8d2cbcc54707853d19c74ae027071789ea1bb12b3ec89` | [Apache-2.0](https://raw.githubusercontent.com/keycloak/keycloak/26.7.4/LICENSE.txt) (`docs/evidence/M01/licenses/keycloak-LICENSE.txt`, `sha256:cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`) | /opt/keycloak/LICENSE.txt | none at checked paths |
| postgres | `17-alpine` | `sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24` | `sha256:aa90e97ee862e558111d34cfb8b2c4bec768c2b039fb791341686928560263b3` | `sha256:79bd7c99e923138f136f8009d6bffa66e21e9d4fda5c0c561b00fc9c90cfe537` | [PostgreSQL](https://raw.githubusercontent.com/postgres/postgres/REL_17_11/COPYRIGHT) (`docs/evidence/M01/licenses/postgres-COPYRIGHT`, `sha256:3d6af92ff8a4c2cdf69afb1cf44edea727922f5cd0cf8b5f72b11cdecac8fdfd`) | none at checked paths | none at checked paths |

## Installed Python packages

All installed non-project distributions match `uv.lock` and have an
installed license file. Package versions, license hashes, and notice
presence are in `inventory.json`.
Packages locked but not installed on this platform: colorama.
