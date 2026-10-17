using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace Vrar.Environment
{
    /// <summary>
    /// A field of grass that follows the viewer.
    ///
    /// The blades are generated into one combined mesh, so the whole field is a
    /// single draw call and the wind motion costs nothing on the CPU — it is all
    /// vertex stage. When the camera walks far enough from where the field was
    /// built, the field is rebuilt around it. That is what lets the grass be
    /// everywhere the viewer goes instead of only where the scene was authored.
    ///
    /// Rebuilding is a visible hitch, so it happens rarely and only past a
    /// threshold: well beyond the shader's fade distance is unused geometry, and
    /// rebuilding on every small step would rebuild constantly.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class GrassField : MonoBehaviour
    {
        [SerializeField] private Material _material;
        [SerializeField, Min(0f)] private float _siteX;
        [SerializeField, Min(0f)] private float _siteZ;

        [Tooltip("Tufts attempted per rebuild. Most candidates are rejected by sampling.")]
        [SerializeField, Min(100)] private int _tufts = 9000;

        [Tooltip("Radius scattered around the viewer.")]
        [SerializeField, Min(10f)] private float _radius = 95f;

        [Tooltip("How far the camera may stray before the field is rebuilt around it.")]
        [SerializeField, Min(5f)] private float _recentreDistance = 40f;

        [Tooltip("Never place grass within this of the camera, or a blade fills the lens.")]
        [SerializeField, Min(0f)] private float _cameraClearance = 9f;

        private Mesh _mesh;
        private MeshRenderer _renderer;
        private Vector3 _centre;
        private bool _built;

        private readonly List<Vector3> _vertices = new List<Vector3>(270000);
        private readonly List<Vector3> _normals = new List<Vector3>(270000);
        private readonly List<Color> _colours = new List<Color>(270000);
        private readonly List<int> _triangles = new List<int>(540000);

        private const int BladesPerTuft = 3;
        private const int SegmentsPerBlade = 2;
        private const float BladeWidth = 0.20f;
        private const float DefaultBladeHeight = 1.5f;

        public MeshFilter Filter { get; private set; }

        private void Awake()
        {
            Filter = gameObject.AddComponent<MeshFilter>();
            _renderer = gameObject.AddComponent<MeshRenderer>();
            _renderer.shadowCastingMode = ShadowCastingMode.Off;
            _renderer.receiveShadows = true;
        }

        /// <summary>Seed the field at a position, for scene build time.</summary>
        public void Configure(Material material, Vector3 site, int tufts, float radius)
        {
            _material = material;
            _siteX = site.x;
            _siteZ = site.z;
            _tufts = tufts;
            _radius = radius;
        }

        private void LateUpdate()
        {
            Camera camera = Camera.main;
            if (camera == null)
            {
                return;
            }

            Vector3 focus = camera.transform.position;

            if (!_built)
            {
                _built = true;
                Rebuild(focus, 0);
                return;
            }

            if ((focus - _centre).sqrMagnitude < _recentreDistance * _recentreDistance)
            {
                return;
            }

            Rebuild(focus, 20261016);
        }

        private void Rebuild(Vector3 centre, int seed)
        {
            if (_material == null || Filter == null)
            {
                return;
            }

            _centre = new Vector3(centre.x, 0f, centre.z);
            Populate(centre, seed);

            if (_mesh == null)
            {
                _mesh = new Mesh { name = "GrassField" };
                Filter.sharedMesh = _mesh;
            }

            _mesh.Clear();
            if (_triangles.Count == 0)
            {
                _renderer.enabled = false;
                return;
            }

            _renderer.enabled = true;
            _renderer.sharedMaterial = _material;

            _mesh.indexFormat = IndexFormat.UInt32;
            _mesh.SetVertices(_vertices);
            _mesh.SetNormals(_normals);
            _mesh.SetColors(_colours);
            _mesh.SetTriangles(_triangles, 0, true);
            _mesh.RecalculateBounds();
        }

        /// <summary>
        /// Scatter candidates around <paramref name="centre"/> and build the blade
        /// geometry. Shared by the editor build path and the runtime rebuild.
        /// </summary>
        public void Populate(Vector3 centre, int seed)
        {
            _vertices.Clear();
            _normals.Clear();
            _colours.Clear();
            _triangles.Clear();

            var random = new System.Random(seed == 0 ? 90210 : seed);
            float bladeHeight = _material != null && _material.HasProperty("_BladeHeight")
                ? _material.GetFloat("_BladeHeight")
                : DefaultBladeHeight;

            var site = new Vector3(_siteX, 0f, _siteZ);

            for (int i = 0; i < _tufts; i++)
            {
                // Sqrt-uniform so density does not pile up at the centre, which is
                // what a plain lerp of the radius gives.
                float angle = (float)random.NextDouble() * Mathf.PI * 2f;
                float radial = Mathf.Sqrt((float)random.NextDouble()) * _radius;
                float x = centre.x + Mathf.Cos(angle) * radial;
                float z = centre.z + Mathf.Sin(angle) * radial;

                TerrainBuilder.WeightsAt(x, z, out float grass, out _, out _);
                if (grass < 0.55f)
                {
                    continue;
                }

                // Keep the foundation pad clear: a machine cannot be serviced
                // through a lawn.
                float dx = x - site.x;
                float dz = z - site.z;
                if (dx * dx + dz * dz < 90f * 90f)
                {
                    continue;
                }

                float vx = x - centre.x;
                float vz = z - centre.z;
                if (vx * vx + vz * vz < _cameraClearance * _cameraClearance)
                {
                    continue;
                }

                float y = TerrainBuilder.HeightAt(x, z) - 0.06f;
                float facing = (float)random.NextDouble() * Mathf.PI * 2f;
                float scale = Mathf.Lerp(0.7f, 1.35f, (float)random.NextDouble());
                float tilt = Mathf.Lerp(0.05f, 0.35f, (float)random.NextDouble());

                for (int b = 0; b < BladesPerTuft; b++)
                {
                    float bladeAngle = facing + (float)(random.NextDouble() - 0.5) * 1.4f;
                    float bladeScale = scale * Mathf.Lerp(0.75f, 1.15f, (float)random.NextDouble());
                    EmitBlade(new Vector3(x, y, z), bladeAngle, bladeHeight * bladeScale, bladeScale, tilt);
                }
            }
        }

        /// <summary>
        /// One tapered blade as a strip of quads: a flat root cross-section
        /// collapsing to a point, which gives the silhouette without an alpha
        /// texture and therefore without another licensed asset.
        /// </summary>
        private void EmitBlade(Vector3 root, float angle, float height, float widthScale, float tilt)
        {
            var forward = new Vector3(Mathf.Cos(angle), 0f, Mathf.Sin(angle));
            var side = new Vector3(-forward.z, 0f, forward.x);
            var lean = new Vector3(Mathf.Cos(angle + 1.2f), 0f, Mathf.Sin(angle + 1.2f)) * tilt;
            var normal = Vector3.Cross(side, Vector3.up).normalized;

            int start = _vertices.Count;

            for (int s = 0; s <= SegmentsPerBlade; s++)
            {
                float t = s / (float)SegmentsPerBlade;
                float halfWidth = BladeWidth * widthScale * (1f - t) * 0.5f;
                var centre = root + Vector3.up * (height * t) + lean * (height * t * t);

                _vertices.Add(centre - side * halfWidth);
                _vertices.Add(centre + side * halfWidth);

                // Darker at the root so a tuft has depth with no texture.
                float shade = Mathf.Lerp(0.55f, 1.05f, t);
                _colours.Add(new Color(shade, shade, shade, 1f));
                _colours.Add(new Color(shade, shade, shade, 1f));

                _normals.Add(normal);
                _normals.Add(normal);
            }

            for (int s = 0; s < SegmentsPerBlade; s++)
            {
                int lowerLeft = start + s * 2;
                int lowerRight = lowerLeft + 1;
                int upperLeft = lowerLeft + 2;
                int upperRight = lowerLeft + 3;

                _triangles.Add(lowerLeft);
                _triangles.Add(upperLeft);
                _triangles.Add(lowerRight);
                _triangles.Add(lowerRight);
                _triangles.Add(upperLeft);
                _triangles.Add(upperRight);
            }
        }
    }
}