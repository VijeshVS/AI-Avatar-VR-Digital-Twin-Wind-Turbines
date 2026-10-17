using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace Vrar.Environment
{
    /// <summary>
    /// Bakes a grass field across the terrain, wherever the terrain will take it.
    ///
    /// Earlier revisions scattered grass in a disc around the viewer and rebuilt
    /// it as the camera moved. That is the wrong shape for this problem: a disc
    /// can only ever be as big as its own radius, so the rest of the landscape is
    /// bare no matter where you stand. Instead the field is baked once over the
    /// whole map, with density falling off as 1/(1+(d/a)²) — dense underfoot,
    /// sparse at the horizon — so a fixed triangle budget buys coverage everywhere
    /// rather than a green circle in front of the lens.
    ///
    /// Blades also grow with distance, which is what lets the sparse far field
    /// still read as grass rather than as speckle.
    /// </summary>
    public static class GrassField
    {
        private const int BladesPerTuft = 3;
        private const int SegmentsPerBlade = 2;
        private const float BladeWidth = 0.19f;

        /// <param name="tufts">
        /// Budget. Each tuft is three blades of four triangles, so this is the
        /// main lever on scene cost.
        /// </param>
        /// <param name="reach">How far out from the site grass is placed.</param>
        /// <param name="falloff">
        /// Distance at which density has halved. Small means a tight green core
        /// and a thin horizon; large means an even spread.
        /// </param>
        public static GameObject Build(Material material, int tufts, float reach, float falloff,
            Vector3 site, Vector3 viewpoint)
        {
            var holder = new GameObject("GrassField");
            if (material == null)
            {
                return holder;
            }

            var vertices = new List<Vector3>(tufts * BladesPerTuft * 6);
            var normals = new List<Vector3>(vertices.Capacity);
            var colours = new List<Color>(vertices.Capacity);
            var triangles = new List<int>(vertices.Capacity * 3);

            float bladeHeight = material.HasProperty("_BladeHeight")
                ? material.GetFloat("_BladeHeight")
                : 1.5f;

            Populate(vertices, normals, colours, triangles, material, tufts, reach, falloff,
                bladeHeight, site, viewpoint);

            if (triangles.Count == 0)
            {
                return holder;
            }

            var mesh = new Mesh { name = "GrassField" };
            mesh.indexFormat = IndexFormat.UInt32;
            mesh.SetVertices(vertices);
            mesh.SetNormals(normals);
            mesh.SetColors(colours);
            mesh.SetTriangles(triangles, 0, true);
            mesh.RecalculateBounds();

            holder.AddComponent<MeshFilter>().sharedMesh = mesh;
            var renderer = holder.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            // Blades are too thin for a shadow map to resolve; a blocky shadow
            // carpet is worse than none.
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = true;

            return holder;
        }

        public static void Populate(List<Vector3> vertices, List<Vector3> normals,
            List<Color> colours, List<int> triangles, Material material, int tufts,
            float reach, float falloff, float bladeHeight, Vector3 site, Vector3 viewpoint)
        {
            var random = new System.Random(90210);

            // Inverse-quadratic radial density, sampled by inverting its CDF.
            // Working in d² makes the integral clean, so no rejection loop and no
            // wasted candidates.
            float uMax = reach * reach / (reach * reach + falloff * falloff);

            for (int i = 0; i < tufts; i++)
            {
                float u = (float)random.NextDouble() * uMax;
                float d = Mathf.Sqrt(falloff * falloff * u / Mathf.Max(1e-5f, 1f - u));
                float angle = (float)random.NextDouble() * Mathf.PI * 2f;

                float x = site.x + Mathf.Cos(angle) * d;
                float z = site.z + Mathf.Sin(angle) * d;

                // Suitability is the terrain's own verdict: grass on gentle,
                // grassy ground only. This is the same weighting the shader uses
                // to pick between the grass, rock and dirt maps.
                TerrainBuilder.WeightsAt(x, z, out float grass, out _, out float dirt);
                if (grass < 0.5f || dirt > 0.45f)
                {
                    continue;
                }

                // The foundation pad is a machine pad, not a lawn.
                float fromSite = Mathf.Sqrt(x * x + z * z);
                if (fromSite < 95f)
                {
                    continue;
                }

                // Never grow a blade through the lens.
                float vx = x - viewpoint.x;
                float vz = z - viewpoint.z;
                if (vx * vx + vz * vz < 100f)
                {
                    continue;
                }

                float y = TerrainBuilder.HeightAt(x, z) - 0.06f;
                float facing = (float)random.NextDouble() * Mathf.PI * 2f;
                float scale = Mathf.Lerp(0.75f, 1.35f, (float)random.NextDouble());
                float tilt = Mathf.Lerp(0.05f, 0.35f, (float)random.NextDouble());

                // Distant blades are scaled up so the sparse far field still
                // covers ground instead of turning into aliasing noise.
                scale *= 1f + d / 130f;

                // Per-tuft colour jitter. A field where every blade shares one
                // green reads as flat plastic; variation is most of what makes it
                // look like ground cover rather than a painted surface.
                float tint = Mathf.Lerp(0.78f, 1.18f, (float)random.NextDouble());
                float warmth = Mathf.Lerp(-0.14f, 0.16f, (float)random.NextDouble());

                for (int b = 0; b < BladesPerTuft; b++)
                {
                    float bladeAngle = facing + (float)(random.NextDouble() - 0.5) * 1.4f;
                    float bladeScale = scale * Mathf.Lerp(0.75f, 1.15f, (float)random.NextDouble());
                    float bladeTint = tint * Mathf.Lerp(0.94f, 1.06f, (float)random.NextDouble());
                    EmitBlade(vertices, normals, colours, triangles,
                        new Vector3(x, y, z), bladeAngle, bladeHeight * bladeScale, bladeScale,
                        tilt, bladeTint, warmth);
                }
            }
        }

        /// <summary>
        /// One tapered blade as a strip of quads: a flat root cross-section
        /// collapsing to a point, which gives the silhouette without an alpha
        /// texture and therefore without another licensed asset.
        /// </summary>
        private static void EmitBlade(List<Vector3> vertices, List<Vector3> normals,
            List<Color> colours, List<int> triangles,
            Vector3 root, float angle, float height, float widthScale, float tilt,
            float tint, float warmth)
        {
            var forward = new Vector3(Mathf.Cos(angle), 0f, Mathf.Sin(angle));
            var side = new Vector3(-forward.z, 0f, forward.x);
            var lean = new Vector3(Mathf.Cos(angle + 1.2f), 0f, Mathf.Sin(angle + 1.2f)) * tilt;
            var normal = Vector3.Cross(side, Vector3.up).normalized;

            int start = vertices.Count;

            for (int s = 0; s <= SegmentsPerBlade; s++)
            {
                float t = s / (float)SegmentsPerBlade;
                float halfWidth = BladeWidth * widthScale * (1f - t) * 0.5f;
                var centre = root + Vector3.up * (height * t) + lean * (height * t * t);

                vertices.Add(centre - side * halfWidth);
                vertices.Add(centre + side * halfWidth);

                // Darker at the root so a tuft has depth, then the per-tuft tint.
                // Warmth nudges some blades toward dry straw and others toward
                // cool green, which is what stops the field reading as one colour.
                float shade = Mathf.Lerp(0.42f, 1.12f, t) * tint;
                var colour = new Color(
                    Mathf.Clamp01(shade * (1f + warmth)),
                    Mathf.Clamp01(shade * (1f + warmth * 0.35f)),
                    Mathf.Clamp01(shade * (1f - warmth * 0.5f)),
                    1f);
                colours.Add(colour);
                colours.Add(colour);

                normals.Add(normal);
                normals.Add(normal);
            }

            for (int s = 0; s < SegmentsPerBlade; s++)
            {
                int lowerLeft = start + s * 2;
                int lowerRight = lowerLeft + 1;
                int upperLeft = lowerLeft + 2;
                int upperRight = lowerLeft + 3;

                triangles.Add(lowerLeft);
                triangles.Add(upperLeft);
                triangles.Add(lowerRight);
                triangles.Add(lowerRight);
                triangles.Add(upperLeft);
                triangles.Add(upperRight);
            }
        }
    }
}