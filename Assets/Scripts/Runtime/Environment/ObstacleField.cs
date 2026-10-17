using System.Collections.Generic;
using UnityEngine;

namespace Vrar.Environment
{
    /// <summary>
    /// Where the planted props are, as solid discs.
    ///
    /// Conifers and boulders are baked into a handful of combined meshes and have
    /// no GameObjects and no colliders at runtime, so this grid is the only
    /// representation of where they stand. It serves two callers: the scatter
    /// passes, which reject a candidate that would grow inside another prop, and
    /// the herd solver, which pushes livestock out of trees they walk into.
    ///
    /// Cells are deliberately wider than the widest footprint, which lets a
    /// footprint be stored in exactly one cell and a query walk a cell range
    /// without deduplicating the hits.
    /// </summary>
    public static class ObstacleField
    {
        private const float CellSize = 40f;

        /// <summary>Cells per axis from the origin. Covers the terrain and well past it.</summary>
        private const int HalfCells = 96;

        private const float HalfExtent = HalfCells * CellSize;

        private static readonly List<Vector3> Positions = new List<Vector3>(2048);
        private static readonly List<float> Radii = new List<float>(2048);
        private static readonly List<int>[] Cells = CreateCells();

        /// <summary>Scratch for <see cref="Overlaps"/>, which callers invoke in a tight loop.</summary>
        private static readonly List<int> Hits = new List<int>(16);

        /// <summary>Number of footprints registered. Boulders included.</summary>
        public static int Count => Positions.Count;

        public static void Clear()
        {
            Positions.Clear();
            Radii.Clear();

            foreach (List<int> cell in Cells)
            {
                cell?.Clear();
            }
        }

        /// <summary>Register a solid disc. Ignores anything outside the grid.</summary>
        public static void Add(Vector3 position, float radius)
        {
            if (radius <= 0f || !InGrid(position))
            {
                return;
            }

            int index = Positions.Count;
            Positions.Add(position);
            Radii.Add(radius);

            CellFor(position)?.Add(index);
        }

        public static Vector3 Position(int index) => Positions[index];

        public static float Radius(int index) => Radii[index];

        /// <summary>True if any registered disc overlaps the disc at <paramref name="position"/>.</summary>
        public static bool Overlaps(Vector3 position, float radius)
        {
            if (!Query(position, radius, Hits))
            {
                return false;
            }

            for (int i = 0; i < Hits.Count; i++)
            {
                if (Touching(position, radius, Hits[i]))
                {
                    return true;
                }
            }

            return false;
        }

        /// <summary>
        /// Fill <paramref name="results"/> with every footprint whose cell overlaps
        /// the query disc. The caller still has to test the actual distance: a cell
        /// hit is a candidate, not a collision.
        /// </summary>
        public static bool Query(Vector3 position, float radius, List<int> results)
        {
            results.Clear();

            int minX = CellIndex(position.x - radius);
            int maxX = CellIndex(position.x + radius);
            int minZ = CellIndex(position.z - radius);
            int maxZ = CellIndex(position.z + radius);

            for (int cz = minZ; cz <= maxZ; cz++)
            {
                for (int cx = minX; cx <= maxX; cx++)
                {
                    List<int> cell = At(cx, cz);
                    if (cell == null)
                    {
                        continue;
                    }

                    results.AddRange(cell);
                }
            }

            return results.Count > 0;
        }

        /// <summary>Flat, ground-plane overlap test between the query disc and a footprint.</summary>
        public static bool Touching(Vector3 position, float radius, int index)
        {
            float reach = radius + Radii[index];
            float dx = position.x - Positions[index].x;
            float dz = position.z - Positions[index].z;
            return dx * dx + dz * dz < reach * reach;
        }

        /// <summary>Unit vector pushing the query disc out of a footprint, or zero if clear.</summary>
        public static Vector3 Separation(Vector3 position, float radius, int index)
        {
            float reach = radius + Radii[index];
            var offset = new Vector3(
                position.x - Positions[index].x,
                0f,
                position.z - Positions[index].z);

            float distance = offset.magnitude;
            if (distance >= reach)
            {
                return Vector3.zero;
            }

            // Exactly coincident has no direction to push along. Anything stable
            // will do; this only happens if a disc is placed inside another.
            if (distance < 1e-4f)
            {
                return new Vector3(1f, 0f, 0f) * (reach - distance);
            }

            return offset / distance * (reach - distance);
        }

        private static List<int>[] CreateCells()
        {
            var cells = new List<int>[HalfCells * HalfCells];
            for (int i = 0; i < cells.Length; i++)
            {
                cells[i] = new List<int>();
            }

            return cells;
        }

        private static bool InGrid(Vector3 position)
        {
            return Mathf.Abs(position.x) <= HalfExtent && Mathf.Abs(position.z) <= HalfExtent;
        }

        private static int CellIndex(float value) =>
            Mathf.Clamp(Mathf.FloorToInt((value + HalfExtent) / CellSize), 0, HalfCells - 1);

        private static List<int> At(int cx, int cz) => Cells[cz * HalfCells + cx];

        private static List<int> CellFor(Vector3 position) =>
            At(CellIndex(position.x), CellIndex(position.z));
    }
}