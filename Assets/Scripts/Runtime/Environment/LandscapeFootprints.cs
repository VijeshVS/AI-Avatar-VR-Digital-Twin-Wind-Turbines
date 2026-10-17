using UnityEngine;

namespace Vrar.Environment
{
    /// <summary>
    /// Persists the baked prop footprints into the scene.
    ///
    /// <see cref="ObstacleField"/> is a plain static, so a domain reload empties it.
    /// The scatter passes repopulate it while the scene is being generated in edit
    /// mode, but at play time nothing would, and the herd solver would silently stop
    /// steering livestock around trees. Capturing the discs as serialized data and
    /// replaying them on Awake makes the runtime layout independent of whether the
    /// domain reloaded.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class LandscapeFootprints : MonoBehaviour
    {
        /// <summary>One entry per planted prop: xyz is the ground position, w the solid radius.</summary>
        [SerializeField] private Vector4[] _footprints = new Vector4[0];

        public int Count => _footprints?.Length ?? 0;

        /// <summary>Snapshot whatever the scatter passes registered into the scene.</summary>
        public void Capture()
        {
            int count = ObstacleField.Count;
            var captured = new Vector4[count];

            for (int i = 0; i < count; i++)
            {
                Vector3 position = ObstacleField.Position(i);
                captured[i] = new Vector4(position.x, position.y, position.z, ObstacleField.Radius(i));
            }

            _footprints = captured;
        }

        private void Awake()
        {
            ObstacleField.Clear();

            if (_footprints == null)
            {
                return;
            }

            for (int i = 0; i < _footprints.Length; i++)
            {
                Vector4 footprint = _footprints[i];
                ObstacleField.Add(new Vector3(footprint.x, footprint.y, footprint.z), footprint.w);
            }
        }
    }
}