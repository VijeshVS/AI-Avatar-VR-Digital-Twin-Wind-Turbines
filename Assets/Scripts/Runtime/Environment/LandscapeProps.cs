using System.Collections.Generic;
using UnityEngine;

namespace Vrar.Environment
{
    /// <summary>
    /// Procedural vegetation and boulders, batched into a few combined meshes.
    ///
    /// Deliberately procedural rather than downloaded: a thousand imported tree
    /// models would blow the pilot's asset budget (FR-1.7 caps the project at 40
    /// models) and a forest of FBX would dominate load time on the 8 GB reference
    /// machine. Three cone silhouettes built from primitives give a believable
    /// treeline for a few dozen triangles each.
    ///
    /// Placement is rejection sampling against the terrain's own height, slope and
    /// layer-weight functions, so nothing floats, nothing grows on a cliff, and
    /// nothing stands on the turbine's foundation pad.
    /// </summary>
    public static class LandscapeProps
    {
        /// <summary>Emits one prop's mesh parts into shared batches.</summary>
        public delegate void ShapeBuilder(Batches batches, Vector3 position, float scale, float rotation);

        /// <summary>
        /// Parts bucketed by material. CombineInstance cannot carry a per-part
        /// material, so a prop with two materials is split into two combined
        /// meshes rather than being flattened to one.
        /// </summary>
        public sealed class Batches
        {
            public readonly List<CombineInstance> Primary = new List<CombineInstance>();
            public readonly List<CombineInstance> Secondary = new List<CombineInstance>();

            public void Add(PrimitiveType type, Matrix4x4 matrix, bool secondary = false)
            {
                Mesh mesh = GetMesh(type);
                if (mesh == null)
                {
                    return;
                }

                var instance = new CombineInstance
                {
                    mesh = mesh,
                    transform = matrix,
                    subMeshIndex = 0
                };

                (secondary ? Secondary : Primary).Add(instance);
            }
        }

        private const float Seed = 20261016f;
        private const float ViewpointClearRadius = 70f;
        private const float PropExtent = 1150f;
        private const int ConiferCount = 700;
        private const int BoulderCount = 260;

        /// <param name="site">World origin: the foundation pad, kept clear.</param>
        /// <param name="viewpoint">
        /// Where the camera stands. Cleared as well, or a 20 m conifer two metres
        /// from the lens fills the frame and swallows the machine it is there to
        /// give scale to.
        /// </param>
        public static GameObject Build(Material foliage, Material bark, Material rock,
            Vector3 site, Vector3 viewpoint)
        {
            var holder = new GameObject("Landscape");

            if (foliage != null || bark != null)
            {
                Scatter(holder.transform, foliage, bark, ConiferCount, BuildConifer, WantsTree, 240f, viewpoint);
            }

            if (rock != null)
            {
                Scatter(holder.transform, rock, null, BoulderCount, BuildBoulder, WantsBoulder, 190f, viewpoint);
            }

            return holder;
        }

        /// <summary>
        /// Rejection-sample positions, then emit combined meshes. One draw call
        /// per material per prop type rather than one per prop.
        /// </summary>
        private static void Scatter(Transform parent, Material primary, Material secondary, int count,
            ShapeBuilder shape, System.Func<float, float, float, bool> wants, float siteClear,
            Vector3 viewpoint)
        {
            var batches = new Batches();
            var random = new System.Random((int)Seed);

            for (int i = 0; i < count; i++)
            {
                float x = (float)(random.NextDouble() * 2.0 - 1.0) * PropExtent;
                float z = (float)(random.NextDouble() * 2.0 - 1.0) * PropExtent;
                float distance = Mathf.Sqrt(x * x + z * z);

                // Keep the foundation pad and its apron clear.
                if (distance < siteClear)
                {
                    continue;
                }

                float fromViewpoint = (x - viewpoint.x) * (x - viewpoint.x) +
                                      (z - viewpoint.z) * (z - viewpoint.z);
                if (fromViewpoint < ViewpointClearRadius * ViewpointClearRadius)
                {
                    continue;
                }

                float y = TerrainBuilder.HeightAt(x, z);
                float slope = Slope(x, z);
                TerrainBuilder.WeightsAt(x, z, out float grass, out float rockWeight, out _);

                if (!wants(grass, rockWeight, slope))
                {
                    continue;
                }

                // Thin with distance so the near field reads dense and the horizon
                // sparse, which is how a real treeline falls away.
                float density = Mathf.Lerp(1f, 0.30f, Mathf.InverseLerp(300f, PropExtent, distance));
                if (random.NextDouble() > density)
                {
                    continue;
                }

                var position = new Vector3(x, y - 0.5f, z);
                float scale = Mathf.Lerp(0.55f, 0.95f, (float)random.NextDouble());
                float rotation = (float)random.NextDouble() * 360f;
                shape(batches, position, scale, rotation);
            }

            Emit(parent, primary, batches.Primary, "foliage");
            if (secondary != null)
            {
                Emit(parent, secondary, batches.Secondary, "bark");
            }
        }

        private static void Emit(Transform parent, Material material, List<CombineInstance> parts, string suffix)
        {
            if (material == null || parts.Count == 0)
            {
                return;
            }

            var combined = new Mesh { name = material.name + "_" + suffix };
            combined.CombineMeshes(parts.ToArray(), true, true);
            combined.RecalculateBounds();

            var go = new GameObject(material.name + "_" + suffix);
            go.transform.SetParent(parent, false);
            go.AddComponent<MeshFilter>().sharedMesh = combined;
            go.AddComponent<MeshRenderer>().sharedMaterial = material;
        }

        private static bool WantsTree(float grass, float rockWeight, float slope)
        {
            return grass > 0.45f && slope < 0.34f;
        }

        private static bool WantsBoulder(float grass, float rockWeight, float slope)
        {
            return rockWeight > 0.16f || slope > 0.26f;
        }

        private static float Slope(float x, float z)
        {
            const float epsilon = 6f;
            float dx = TerrainBuilder.HeightAt(x + epsilon, z) - TerrainBuilder.HeightAt(x - epsilon, z);
            float dz = TerrainBuilder.HeightAt(x, z + epsilon) - TerrainBuilder.HeightAt(x, z - epsilon);
            return Mathf.Sqrt(dx * dx + dz * dz) / (2f * epsilon);
        }

        /// <summary>A conifer: tapered trunk plus three stacked cones.</summary>
        private static void BuildConifer(Batches batches, Vector3 position, float scale, float rotation)
        {
            var matrix = Matrix4x4.TRS(position, Quaternion.Euler(0f, rotation, 0f), Vector3.one * scale);

            batches.Add(PrimitiveType.Cylinder, matrix *
                Matrix4x4.TRS(new Vector3(0f, 4.5f, 0f), Quaternion.identity, new Vector3(0.7f, 4.5f, 0.7f)),
                secondary: true);

            batches.Add(PrimitiveType.Cylinder, matrix *
                Matrix4x4.TRS(new Vector3(0f, 11f, 0f), Quaternion.identity, new Vector3(9f, 4.5f, 9f)));
            batches.Add(PrimitiveType.Cylinder, matrix *
                Matrix4x4.TRS(new Vector3(0f, 16.5f, 0f), Quaternion.identity, new Vector3(7f, 3.6f, 7f)));
            batches.Add(PrimitiveType.Cylinder, matrix *
                Matrix4x4.TRS(new Vector3(0f, 21f, 0f), Quaternion.identity, new Vector3(4.4f, 2.6f, 4.4f)));
        }

        /// <summary>A boulder: a stretched, tilted low-poly sphere.</summary>
        private static void BuildBoulder(Batches batches, Vector3 position, float scale, float rotation)
        {
            var matrix = Matrix4x4.TRS(
                position,
                Quaternion.Euler(rotation * 0.13f % 40f - 20f, rotation, rotation * 0.07f % 30f - 15f),
                new Vector3(scale, scale * 0.72f, scale * 1.15f));

            batches.Add(PrimitiveType.Sphere, matrix *
                Matrix4x4.TRS(new Vector3(0f, 0.35f * scale, 0f), Quaternion.identity, Vector3.one));
        }

        private static readonly Dictionary<PrimitiveType, Mesh> MeshCache = new Dictionary<PrimitiveType, Mesh>();

        /// <summary>
        /// GetPrimitiveMesh, not CreatePrimitive: no collider and no GameObject per
        /// part. Creating thousands of throwaway objects and destroying them again
        /// is the single easiest way to make scene generation take minutes.
        /// </summary>
        private static Mesh GetMesh(PrimitiveType type)
        {
            if (MeshCache.TryGetValue(type, out Mesh cached) && cached != null)
            {
                return cached;
            }

            var temporary = GameObject.CreatePrimitive(type);
            Mesh mesh = temporary.GetComponent<MeshFilter>().sharedMesh;
            if (Application.isPlaying)
            {
                Object.Destroy(temporary);
            }
            else
            {
                Object.DestroyImmediate(temporary);
            }

            MeshCache[type] = mesh;
            return mesh;
        }
    }
}