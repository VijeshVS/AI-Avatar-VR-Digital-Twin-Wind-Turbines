using UnityEngine;

namespace Vrar.Environment
{
    /// <summary>
    /// Scatters herds of grazing animals across the landscape.
    ///
    /// Each herd is given a home range and kept inside it, so the animals read as
    /// belonging to the terrain rather than drifting off toward the horizon.
    /// Placement reuses the terrain's own height and layer weights: nothing
    /// spawns on a cliff, in the water-like flats, on the foundation pad, or close
    /// enough to the camera to fill the frame.
    /// </summary>
    public static class Livestock
    {
        private struct Herd
        {
            public int Count;
            public float Scale;
            public Color Colour;
            public float WalkSpeed;
            public float Range;
        }

        private static readonly Herd[] Species =
        {
            // Sheep: small, numerous, tightly grouped.
            new Herd { Count = 7, Scale = 0.85f, Colour = new Color(0.86f, 0.85f, 0.80f), WalkSpeed = 1.0f, Range = 55f },
            // Cattle: larger, slower, wider ranging.
            new Herd { Count = 5, Scale = 1.35f, Colour = new Color(0.34f, 0.24f, 0.18f), WalkSpeed = 0.85f, Range = 80f },
            // Deer: a third herd, lighter and quicker, further out.
            new Herd { Count = 6, Scale = 1.05f, Colour = new Color(0.52f, 0.38f, 0.24f), WalkSpeed = 1.6f, Range = 120f },
        };

        public static GameObject Build(Vector3 site, Vector3 viewpoint, float extent = 900f)
        {
            var holder = new GameObject("Livestock");
            var random = new System.Random(4711);
            int seed = 1;

            for (int h = 0; h < Species.Length; h++)
            {
                Herd herd = Species[h];

                // Cattle range widest, so they get placed first and furthest out.
                float search = herd.Range + 140f;
                if (!TryFindSpot(site, viewpoint, extent, search, herd.Range, out Vector3 home))
                {
                    continue;
                }

                var parent = new GameObject($"Herd_{h}");
                parent.transform.SetParent(holder.transform, false);

                for (int i = 0; i < herd.Count; i++)
                {
                    // Cluster tightly: animals scattered across a kilometre read as
                    // isolated props, not as livestock.
                    float angle = (float)random.NextDouble() * Mathf.PI * 2f;
                    float radius = Mathf.Sqrt((float)random.NextDouble()) * herd.Range * 0.35f;
                    var offset = new Vector3(Mathf.Cos(angle) * radius, 0f, Mathf.Sin(angle) * radius);

                    Vector3 position = home + offset;
                    position.y = TerrainBuilder.HeightAt(position.x, position.z);

                    Animal.Spawn(parent.transform, position, herd.Scale,
                        herd.Colour, herd.WalkSpeed * Mathf.Lerp(0.85f, 1.15f, (float)random.NextDouble()),
                        seed++);
                }
            }

            return holder;
        }

        /// <summary>
        /// A believable home: gentle ground, grass, clear of the pad and far
        /// enough from the viewer not to be a surprise at the lens.
        /// </summary>
        private static bool TryFindSpot(Vector3 site, Vector3 viewpoint, float extent,
            float search, float clearance, out Vector3 spot)
        {
            var random = new System.Random((int)(search * 1000) + (int)clearance);
            spot = default;

            for (int attempt = 0; attempt < 220; attempt++)
            {
                float angle = (float)random.NextDouble() * Mathf.PI * 2f;
                float radial = Mathf.Sqrt((float)random.NextDouble()) * search;
                var candidate = new Vector3(
                    site.x + Mathf.Cos(angle) * radial,
                    0f,
                    site.z + Mathf.Sin(angle) * radial);

                float fromSite = Mathf.Sqrt(candidate.x * candidate.x + candidate.z * candidate.z);
                if (fromSite < 200f || fromSite > extent)
                {
                    continue;
                }

                float vx = candidate.x - viewpoint.x;
                float vz = candidate.z - viewpoint.z;
                if (vx * vx + vz * vz < clearance * clearance)
                {
                    continue;
                }

                TerrainBuilder.WeightsAt(candidate.x, candidate.z, out float grass, out _, out float dirt);
                if (grass < 0.5f || dirt > 0.4f)
                {
                    continue;
                }

                candidate.y = TerrainBuilder.HeightAt(candidate.x, candidate.z);
                spot = candidate;
                return true;
            }

            return false;
        }
    }
}