# Asset manifest

Every 3D, texture and audio asset in the build, with its source and licence.
Required by PRD **FR-1.3** and **NFR-4.2**. Zero paid assets, plugins or tools
(**NFR-4.1**).

## Provenance

Assets fall into two groups.

**Procedural — no source, nothing to attribute.** The turbine, the terrain mesh,
the vegetation and the boulders are all generated from code at scene-build time:

| Asset | Generator | Notes |
| --- | --- | --- |
| Wind turbine | `TurbineFactory.cs` | Unity primitives, real-world scale |
| Terrain | `TerrainBuilder.cs` | Analytic ridged/fbm heightfield, 224² grid |
| Conifers, boulders | `LandscapeProps.cs` | Primitives, batched into combined meshes |
| Grass | `GrassField.cs` + `GrassWind.shader` | Procedural blades, wind in the vertex stage |
| Sheep, cattle, deer | `Animal.cs`, `Livestock.cs` | Primitives, procedural gait and wander |
| Terrain shader | `Assets/Shaders/TerrainBlend.shader` | Hand-written URP HLSL |
| Grass shader | `Assets/Shaders/GrassWind.shader` | Hand-written URP HLSL |
| Drivetrain hum, alarm | `ProceduralAudio.cs` | Synthesised at runtime, no audio files |

**Downloaded — CC0, from Poly Haven.** Poly Haven publishes everything under
CC0 (public domain dedication), which satisfies **FR-1.1** and needs no
per-asset attribution, though the source is recorded here regardless.

| Asset | File | Source | Licence |
| --- | --- | --- | --- |
| Sky (HDRI 1k) | `Assets/Environment/Sky/hilly_terrain_sky.hdr` | <https://polyhaven.com/a/hilly_terrain_01_puresky> | CC0 |
| Grass diffuse + normal | `Assets/Environment/Textures/grass_ground_*.jpg` | <https://polyhaven.com/a/grass_ground> | CC0 |
| Rock diffuse + normal | `Assets/Environment/Textures/aerial_rocks_04_*.jpg` | <https://polyhaven.com/a/aerial_rocks_04> | CC0 |
| Dirt diffuse + normal | `Assets/Environment/Textures/brown_mud_02_*.jpg` | <https://polyhaven.com/a/brown_mud_02> | CC0 |

All six texture maps and the HDRI are 1k, chosen against the pilot's binding
constraint — an 8 GB unified-memory machine (PRD §6.12). Total download is
roughly 7.5 MB.

## Dimensional ground truth

No imported geometry is dimensioned to an OEM turbine. Proportions come from the
public-domain reference specification required by **FR-1.5**: the IEA Wind Task 37
WP2.1 land-based geared reference turbine. That supplies numbers only; the shapes
are procedural.

## Sources considered and rejected

No CC0 catalogue reachable without an interactive browser session carries a
Unity-native animated quadruped, so the livestock is generated in code:

| Source | Licence | Why rejected |
| --- | --- | --- |
| Kenney "Animal Pack" | CC0 | PNG sprite sheets only — no 3D geometry |
| Quaternius "Ultimate Animated Animals" | CC0 | Hosted on Google Drive and itch.io; no direct file URL |
| `sirrobzeroone/Animal_Models` | CC0 | minetest `.b3d`, which Unity does not import (FR-1.2) |
| `skywolfgamestudios/CC0Tree` | CC0 | Props and trees; no animals |

If real animal models are wanted later, the drop-in point is `Animal.BuildBody` —
replacing it with an FBX import leaves the wander behaviour and gait intact.

## Outstanding obligation

**NFR-4.5 / §7.15 — licensing is a live obligation, not a one-off.** Free-store
licences can change or be revoked. Re-check every entry above before any public
release or academic submission, and keep this file in step with the assets.