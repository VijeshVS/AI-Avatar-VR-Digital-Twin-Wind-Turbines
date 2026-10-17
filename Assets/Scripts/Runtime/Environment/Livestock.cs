using System.Collections.Generic;
using UnityEngine;

namespace Vrar.Environment
{
    /// <summary>
    /// Scatters herds of grazing animals across the landscape.
    ///
    /// Each herd is placed in its own distance band rather than all being dropped
    /// near the turbine, so the pasture reads as stocked across the whole map and
    /// there is always something in the mid-ground. Bands are non-overlapping by
    /// design: herds seeded from the same search ring used to clump, because
    /// rejection sampling kept landing on the same good ground.
    ///
    /// Placement reuses the terrain's own height and layer weights: nothing
    /// spawns on a cliff, on bare rock, on the foundation pad, or close enough to
    /// the camera to fill the frame.
    ///
    /// Animals are solid. Each herd is packed so that no two members can touch, no
    /// member starts inside a conifer, and every member is walled into a home range
    /// big enough to hold the whole herd — because at this scale a herd that shares
    /// ground with its neighbour spends its life shoving. Movement is then resolved
    /// by <see cref="HerdSolver"/> rather than left to chance.
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
            public float BandNear;
            public float BandFar;

            /// <summary>Per-animal colour jitter, so a herd is not one flat tone.</summary>
            public float Variation;
        }

        /// <summary>
        /// Deliberately far above life size. At the distances these herds range
        /// over, a correctly sized sheep is a couple of pixels and the pasture
        /// reads as empty. Sized for legibility at the overview camera.
        /// </summary>
        private static readonly Herd[] Species =
        {
            new Herd { Count = 8, Scale = 11.4f, Colour = new Color(0.86f, 0.85f, 0.80f), WalkSpeed = 1.0f, Range = 60f,  BandNear = 170f, BandFar = 330f,  Variation = 0.06f },
            new Herd { Count = 6, Scale = 17.4f, Colour = new Color(0.34f, 0.24f, 0.18f), WalkSpeed = 0.85f, Range = 85f,  BandNear = 320f, BandFar = 520f,  Variation = 0.10f },
            new Herd { Count = 7, Scale = 13.8f, Colour = new Color(0.52f, 0.38f, 0.24f), WalkSpeed = 1.6f, Range = 120f, BandNear = 500f, BandFar = 720f,  Variation = 0.12f },
            new Herd { Count = 5, Scale = 11.4f, Colour = new Color(0.82f, 0.80f, 0.74f), WalkSpeed = 1.1f, Range = 70f,  BandNear = 700f, BandFar = 980f,  Variation = 0.06f },
            new Herd { Count = 4, Scale = 17.4f, Colour = new Color(0.30f, 0.21f, 0.16f), WalkSpeed = 0.8f, Range = 90f,  BandNear = 960f, BandFar = 1200f, Variation = 0.10f },
        };

        /// <summary>
        /// Centre-to-centre gap between two herd members, as a multiple of one
        /// animal's footprint radius. Above the 2.0 that merely avoids touching, so
        /// there is room to squeeze past and a herd reads as a herd rather than a
        /// hedge of interlocked bodies.
        /// </summary>
        private const float SeparationFactor = 2.25f;

        /// <summary>Extra ground an animal keeps clear of a tree it grazes beside.</summary>
        private const float TreeClearance = 3f;

        /// <summary>Attempts per herd member at a given packing disc size.</summary>
        private const int PlacementAttempts = 96;

        /// <summary>How many times the packing disc may grow before a member is dropped.</summary>
        private const int GrowthSteps = 5;

        public static GameObject Build(Vector3 site, Vector3 viewpoint)
        {
            var holder = new GameObject("Livestock");
            var random = new System.Random(4711);
            int seed = 1;

            // Herds are placed one at a time, and each new home has to clear the
            // reach of the herds already placed, so two pastures never grow into one.
            var homes = new List<Vector3>(Species.Length);
            var reaches = new List<float>(Species.Length);

            for (int h = 0; h < Species.Length; h++)
            {
                Herd herd = Species[h];
                float footprint = Animal.FootprintRadius * herd.Scale;
                float gap = SeparationFactor * footprint;
                float homeRadius = ClusterRadius(herd.Count, footprint) * 1.15f;

                if (!TryFindSpot(site, viewpoint, herd, homes, reaches, homeRadius + footprint, out Vector3 home))
                {
                    continue;
                }

                homes.Add(home);
                reaches.Add(homeRadius + footprint);

                var parent = new GameObject($"Herd_{h}");
                parent.transform.SetParent(holder.transform, false);

                var members = new List<Vector3>(herd.Count);
                for (int i = 0; i < herd.Count; i++)
                {
                    Vector3 position;
                    if (!TryPlaceHerd(random, home, herd.Count, gap, footprint, homeRadius, members, out position))
                    {
                        continue;
                    }

                    members.Add(position);

                    Color coat = Jitter(herd.Colour, herd.Variation, (float)random.NextDouble() * 2f - 1f);
                    Animal.Spawn(parent.transform, position, herd.Scale, coat,
                        herd.WalkSpeed * Mathf.Lerp(0.85f, 1.15f, (float)random.NextDouble()), seed++,
                        home, homeRadius);
                }
            }

            holder.AddComponent<HerdSolver>();
            return holder;
        }

        /// <summary>
        /// Radius of a disc that holds <paramref name="count"/> non-touching animals.
        ///
        /// sqrt(count) is the area term for packing discs into a disc and the leading
        /// constant is the slack a random pack needs to clear the minimum separation,
        /// plus a whole footprint so the outermost animal's nose stays inside.
        /// </summary>
        private static float ClusterRadius(int count, float footprint)
        {
            float gap = SeparationFactor * footprint;
            return Mathf.Sqrt(count) * gap * 0.75f + footprint;
        }

        /// <summary>
        /// Pack one member into the herd's disc. If the disc is too tight for the
        /// number of animals left to fit, grow it and try again rather than dropping
        /// the animal or squeezing it in on top of a neighbour.
        /// </summary>
        private static bool TryPlaceHerd(System.Random random, Vector3 home, int herdSize, float gap,
            float footprint, float homeRadius, List<Vector3> members, out Vector3 position)
        {
            float cluster = ClusterRadius(herdSize, footprint);

            for (int step = 0; step <= GrowthSteps; step++)
            {
                // Every member is offered the whole herd's disc, so the herd spreads
                // evenly instead of the first arrivals taking the middle and the last
                // being exiled to the rim. The disc grows only when the herd will not
                // otherwise fit, and never past the herd's home range, because the
                // solver would clamp a member straight back inside it.
                if (TryPlaceMember(random, home, Mathf.Min(cluster, homeRadius), gap, footprint, members,
                        out position))
                {
                    return true;
                }

                cluster *= 1.2f;
            }

            position = default;
            return false;
        }

        /// <summary>
        /// Find a gap in the herd that no already-placed animal reaches into, on
        /// ground the terrain says will hold a grazer, and out of the camera's lap.
        /// </summary>
        private static bool TryFindSpot(Vector3 site, Vector3 viewpoint, Herd herd,
            List<Vector3> homes, List<float> reaches, float herdReach, out Vector3 spot)
        {
            var random = new System.Random((int)(herd.BandNear * 31f + herd.BandFar));
            spot = default;

            for (int attempt = 0; attempt < 400; attempt++)
            {
                // Sqrt-uniform within the band, so the band is filled evenly by
                // area rather than bunched at its inner edge.
                float near = herd.BandNear;
                float far = herd.BandFar;
                float d = Mathf.Sqrt(near * near + (float)random.NextDouble() * (far * far - near * near));
                float angle = (float)random.NextDouble() * Mathf.PI * 2f;

                var candidate = new Vector3(
                    site.x + Mathf.Cos(angle) * d,
                    0f,
                    site.z + Mathf.Sin(angle) * d);

                float vx = candidate.x - viewpoint.x;
                float vz = candidate.z - viewpoint.z;
                if (vx * vx + vz * vz < herd.Range * herd.Range)
                {
                    continue;
                }

                bool clearOfHerds = true;
                for (int i = 0; i < homes.Count; i++)
                {
                    float separation = (herdReach + reaches[i]) * 0.9f;
                    float dx = candidate.x - homes[i].x;
                    float dz = candidate.z - homes[i].z;
                    if (dx * dx + dz * dz < separation * separation)
                    {
                        clearOfHerds = false;
                        break;
                    }
                }

                if (!clearOfHerds)
                {
                    continue;
                }

                TerrainBuilder.WeightsAt(candidate.x, candidate.z, out float grass, out _, out float dirt);
                if (grass < 0.45f || dirt > 0.45f)
                {
                    continue;
                }

                candidate.y = TerrainBuilder.HeightAt(candidate.x, candidate.z);
                spot = candidate;
                return true;
            }

            return false;
        }

        /// <summary>
        /// Drop one animal into the herd's disc, sqrt-uniform so the herd thins
        /// towards its rim rather than forming a ring, rejecting anything that would
        /// touch a neighbour, stand in a tree, or graze off the grass.
        /// </summary>
        private static bool TryPlaceMember(System.Random random, Vector3 home, float cluster, float gap,
            float footprint, List<Vector3> members, out Vector3 position)
        {
            for (int attempt = 0; attempt < PlacementAttempts; attempt++)
            {
                float angle = (float)random.NextDouble() * Mathf.PI * 2f;
                float radius = Mathf.Sqrt((float)random.NextDouble()) * cluster;
                var candidate = new Vector3(
                    home.x + Mathf.Cos(angle) * radius,
                    0f,
                    home.z + Mathf.Sin(angle) * radius);

                bool clear = true;
                for (int i = 0; i < members.Count; i++)
                {
                    float dx = candidate.x - members[i].x;
                    float dz = candidate.z - members[i].z;
                    if (dx * dx + dz * dz < gap * gap)
                    {
                        clear = false;
                        break;
                    }
                }

                if (!clear)
                {
                    continue;
                }

                TerrainBuilder.WeightsAt(candidate.x, candidate.z, out float grass, out _, out float dirt);
                if (grass < 0.45f || dirt > 0.45f)
                {
                    continue;
                }

                // Conifers are solid. An animal that starts inside one spends its
                // first frames being shoved out of it, and the shove is visible.
                if (ObstacleField.Overlaps(candidate, footprint + TreeClearance))
                {
                    continue;
                }

                candidate.y = TerrainBuilder.HeightAt(candidate.x, candidate.z);
                position = candidate;
                return true;
            }

            position = default;
            return false;
        }

        /// <summary>Lighten or darken a coat so no two animals match exactly.</summary>
        private static Color Jitter(Color colour, float amount, float direction)
        {
            float scale = 1f + amount * direction;
            return new Color(
                Mathf.Clamp01(colour.r * scale),
                Mathf.Clamp01(colour.g * scale),
                Mathf.Clamp01(colour.b * scale),
                1f);
        }
    }
}