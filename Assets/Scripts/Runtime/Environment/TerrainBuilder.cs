using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace Vrar.Environment
{
    /// <summary>
    /// Builds the ground the turbine stands on as a single mesh.
    ///
    /// The shape is analytic rather than sampled: ridged noise over a few octaves,
    /// shaped by a mask that forces a flat pad under the turbine so the machine
    /// sits on level ground the way a real foundation would. That keeps the whole
    /// terrain a pure function of world position, so the scatter and the camera
    /// can query the same height function without keeping a heightmap in memory.
    ///
    /// Layer weights ride in vertex colour (r grass, g rock, b dirt) and are
    /// derived from height and slope, which is why the shader needs no splat map.
    /// </summary>
    public static class TerrainBuilder
    {
        /// <summary>Half-extent of the square terrain patch, in metres.</summary>
        public const float Extent = 1400f;

        /// <summary>Fully flat radius under the turbine, the foundation pad.</summary>
        private const float PadRadius = 95f;

        /// <summary>Outer edge of the summit plateau the machine stands on.</summary>
        private const float PlateauRadius = 300f;

        /// <summary>
        /// Elevation of the plateau, and therefore of the turbine origin. A wind
        /// farm sits on high ground, and it keeps the sight lines to the drive
        /// train clear of the intervening ridges.
        /// </summary>
        public const float PadHeight = 104f;

        private const int GridResolution = 224;
        private const float MaxHeight = 300f;

        /// <summary>
        /// Ground height at a world position. Shared by the mesh builder, the
        /// scatterer and the camera solver, so they can never disagree.
        /// </summary>
        public static float HeightAt(float x, float z)
        {
            float nx = x / Extent;
            float nz = z / Extent;

            // Ridged multifractal: folded noise reads as eroded rock rather than
            // the rolling dunes plain fractal noise gives.
            // Offset the noise fields: an unshifted one is symmetric about the
            // origin, which puts a feature directly under the machine.
            float ridge = Ridged(nx * 1.7f + 11.3f, nz * 1.7f - 4.1f, 5);
            float rolling = Fbm(nx * 0.85f - 3.7f, nz * 0.85f + 8.2f, 4);
            float shape = ridge * 0.72f + rolling * 0.28f;
            float surrounding = shape * MaxHeight;

            float distance = Mathf.Sqrt(x * x + z * z);

            // One blend from a broad summit down to the surrounding hills, rather
            // than a flat pad inside a bowl. A basin puts the turbine in a hole
            // with a ridge in front of it, which hides the machine completely.
            // Normalise first, then smooth. Mathf.SmoothStep takes an already
            // normalised t and interpolates between two *values* — it clamps t to
            // [0,1] rather than mapping it across the range. Passing a distance in
            // metres there silently returns the upper edge for every sample beyond
            // it, which flattens the whole landscape into one height.
            float fall = Mathf.SmoothStep(0f, 1f,
                Mathf.InverseLerp(PadRadius * 2.2f, PlateauRadius * 2.6f, distance));
            return Mathf.Lerp(PadHeight, surrounding, fall);
        }

        /// <summary>
        /// Layer weights at a world position: rock on steep ground and high up,
        /// dirt on the pad and in the flats, grass everywhere else.
        /// </summary>
        public static void WeightsAt(float x, float z, out float grass, out float rock, out float dirt)
        {
            float height = HeightAt(x, z);
            float slope = SlopeAt(x, z);

            // Slope in [0,1]: 0 flat, 1 vertical.
            float steep = Mathf.InverseLerp(0.32f, 0.62f, slope);
            float alpine = Mathf.InverseLerp(PadHeight + 40f, PadHeight + 150f, height);
            rock = Mathf.Clamp01(Mathf.Max(steep, alpine));

            float distance = Mathf.Sqrt(x * x + z * z);
            float bare = Mathf.Clamp01(
                Mathf.InverseLerp(PadRadius * 1.25f, PadRadius * 0.55f, distance) * 0.8f
                + Mathf.InverseLerp(0.18f, 0.34f, slope) * 0.4f);
            dirt = Mathf.Clamp01(bare - rock * 0.8f);

            grass = Mathf.Clamp01(1f - rock - dirt);
        }

        private static float SlopeAt(float x, float z)
        {
            const float epsilon = 6f;
            float dx = HeightAt(x + epsilon, z) - HeightAt(x - epsilon, z);
            float dz = HeightAt(x, z + epsilon) - HeightAt(x, z - epsilon);
            return Mathf.Sqrt(dx * dx + dz * dz) / (2f * epsilon);
        }

        public static GameObject Build(Shader shader, Material material)
        {
            int vertices = GridResolution + 1;
            var positions = new Vector3[vertices * vertices];
            var normals = new Vector3[vertices * vertices];
            var colors = new Color[vertices * vertices];
            var indices = new int[vertices * vertices * 6];

            float step = Extent * 2f / GridResolution;

            for (int z = 0; z < vertices; z++)
            {
                for (int x = 0; x < vertices; x++)
                {
                    float wx = -Extent + x * step;
                    float wz = -Extent + z * step;
                    float height = HeightAt(wx, wz);

                    int index = z * vertices + x;
                    positions[index] = new Vector3(wx, height, wz);

                    float epsilon = step;
                    float dx = HeightAt(wx + epsilon, wz) - HeightAt(wx - epsilon, wz);
                    float dz = HeightAt(wx, wz + epsilon) - HeightAt(wx, wz - epsilon);
                    normals[index] = new Vector3(-dx, 2f * epsilon, -dz).normalized;

                    WeightsAt(wx, wz, out float grass, out float rock, out float dirt);
                    colors[index] = new Color(grass, rock, dirt, 1f);
                }
            }

            int triangle = 0;
            for (int z = 0; z < GridResolution; z++)
            {
                for (int x = 0; x < GridResolution; x++)
                {
                    int i = z * vertices + x;
                    int right = i + 1;
                    int up = i + vertices;
                    int upRight = up + 1;

                    // Two triangles per cell, wound so the face points up.
                    indices[triangle++] = i; indices[triangle++] = up; indices[triangle++] = right;
                    indices[triangle++] = right; indices[triangle++] = up; indices[triangle++] = upRight;
                }
            }

            var mesh = new Mesh { name = "Terrain" };
            mesh.indexFormat = vertices * vertices > 65000 ? IndexFormat.UInt32 : IndexFormat.UInt16;
            mesh.vertices = positions;
            mesh.normals = normals;
            mesh.colors = colors;
            mesh.SetTriangles(indices, 0);
            mesh.RecalculateBounds();

            var holder = new GameObject("Terrain");
            var filter = holder.AddComponent<MeshFilter>();
            filter.sharedMesh = mesh;
            var renderer = holder.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material != null ? material : DefaultMaterial(shader);

            return holder;
        }

        // ---- Noise ------------------------------------------------------------
        // Shared with LandscapeProps so the scatter and the ground agree.

        public static float Fbm(float x, float y, int octaves)
        {
            float total = 0f;
            float amplitude = 0.5f;
            float frequency = 1f;
            for (int i = 0; i < octaves; i++)
            {
                total += ValueNoise(x * frequency, y * frequency) * amplitude;
                frequency *= 2.03f;
                amplitude *= 0.5f;
            }

            return total;
        }

        public static float Ridged(float x, float y, int octaves)
        {
            float total = 0f;
            float amplitude = 0.5f;
            float frequency = 1f;
            for (int i = 0; i < octaves; i++)
            {
                float n = 1f - Mathf.Abs(ValueNoise(x * frequency, y * frequency) * 2f - 1f);
                total += n * n * amplitude;
                frequency *= 2.07f;
                amplitude *= 0.5f;
            }

            return Mathf.Clamp01(total * 1.4f);
        }

        public static float ValueNoise(float x, float y)
        {
            int xi = Mathf.FloorToInt(x);
            int yi = Mathf.FloorToInt(y);
            float xf = x - xi;
            float yf = y - yi;

            // Smootherstep: value noise leaves visible grid creases with linear
            // blending, and the ridged fold amplifies them.
            float u = xf * xf * xf * (xf * (xf * 6f - 15f) + 10f);
            float v = yf * yf * yf * (yf * (yf * 6f - 15f) + 10f);

            float a = Hash(xi, yi);
            float b = Hash(xi + 1, yi);
            float c = Hash(xi, yi + 1);
            float d = Hash(xi + 1, yi + 1);

            return Mathf.Lerp(Mathf.Lerp(a, b, u), Mathf.Lerp(c, d, u), v);
        }

        private static float Hash(int x, int y)
        {
            unchecked
            {
                int h = x * 374761393 + y * 668265263;
                h = (h ^ (h >> 13)) * 1274126177;
                return ((h ^ (h >> 16)) & 0x7fffffff) / (float)0x7fffffff;
            }
        }

        private static Material DefaultMaterial(Shader shader)
        {
            if (shader == null)
            {
                shader = Shader.Find("Universal Render Pipeline/Lit");
            }

            var material = new Material(shader) { name = "TerrainBlend" };
            return material;
        }
    }
}