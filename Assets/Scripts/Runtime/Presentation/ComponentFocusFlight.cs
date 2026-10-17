using UnityEngine;
using Vrar.Avatar;
using Vrar.Turbine;

namespace Vrar.Presentation
{
    /// <summary>
    /// Flies the viewer to whichever component is focused.
    ///
    /// Owns the framing maths and nothing else: it re-reads the focused avatar's
    /// world bounds every frame and hands a camera position and aim point to
    /// <see cref="SimulatedHmdRig"/>. Re-reading rather than framing once matters
    /// because the rotor turns — a camera framed once at the blade set would
    /// drift off it within a second.
    ///
    /// Silently does nothing when there is no viewer, so tests and headless
    /// captures can construct the HUD without a camera in the scene.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class ComponentFocusFlight : MonoBehaviour
    {
        [SerializeField, Min(0.2f)] private float _fill = 0.62f;
        [SerializeField, Min(1f)] private float _maxRadius = 22f;
        [SerializeField, Min(1f)] private float _minDistance = 6f;
        [SerializeField, Range(0.5f, 2f)] private float _conservativeAspect = 4f / 3f;

        private TurbineRig _rig;
        private SimulatedHmdRig _viewer;
        private Camera _camera;
        private ComponentFocus _focus;
        private bool _returning;

        /// <summary>The pose to fly back to once focus is cleared.</summary>
        private SimulatedHmdRig.CameraPose? _returnPose;
        private Vector3 _approachDirection;

        public bool IsActive => _focus != null && _focus.HasFocus && _viewer != null;

        // Exposed for the headless capture diagnostics.
        public SimulatedHmdRig Viewer => _viewer;
        public int LateUpdateTicks { get; private set; }
        public bool Returning => _returning;
        public Vector3 LastBoundsCenter { get; private set; }
        public float LastFramingDistance { get; private set; }
        public Vector3 LastTargetPosition { get; private set; }

        public void Bind(TurbineRig rig, ComponentFocus focus)
        {
            _rig = rig;
            _focus = focus;
            _viewer = FindFirstObjectByType<SimulatedHmdRig>();
            _camera = Camera.main;

            if (_focus != null)
            {
                _focus.Changed += OnFocusChanged;
                OnFocusChanged();
            }
        }

        private void OnDestroy()
        {
            if (_focus != null)
            {
                _focus.Changed -= OnFocusChanged;
            }
        }

        private void OnFocusChanged()
        {
            if (_focus == null || _viewer == null)
            {
                return;
            }

            if (_focus.HasFocus)
            {
                if (_returnPose == null)
                {
                    // Remember where focus was entered from. Recapturing on every
                    // switch would make Escape return to the last part inspected
                    // rather than to the overview.
                    _returnPose = _viewer.CapturePose();
                    CaptureApproachDirection();
                }

                _returning = false;
                return;
            }

            // Closing focus flies the camera back to where it was when focus was
            // entered, rather than stranding the viewer over the drive train.
            if (_returnPose.HasValue)
            {
                _viewer.AutoFlyTo(_returnPose.Value.Position, _returnPose.Value.LookAt);
                _returning = true;
            }
            else
            {
                _viewer.EndAutoFly();
            }
        }

        /// <summary>
        /// Fix the direction the camera approaches a component from, taken once
        /// when focus opens.
        ///
        /// Recomputing it every frame from the camera's current position makes the
        /// target position itself move as the camera moves — the framing chases
        /// its own tail and the approach curves instead of running straight in.
        /// </summary>
        private void CaptureApproachDirection()
        {
            _approachDirection = Vector3.zero;

            ComponentAvatar avatar = _rig != null && _focus != null ? _rig.Avatar(_focus.ComponentId) : null;
            if (avatar == null || !TryGetWorldBounds(avatar, out Bounds bounds))
            {
                return;
            }

            Vector3 outward = _viewer.EyePosition - bounds.center;
            outward.y = 0f;
            if (outward.sqrMagnitude < 0.01f)
            {
                outward = -_viewer.transform.forward;
                outward.y = 0f;
            }

            if (outward.sqrMagnitude < 0.01f)
            {
                return;
            }

            _approachDirection = outward.normalized;
        }

        private void LateUpdate()
        {
            if (_returning)
            {
                TickReturn();
                return;
            }

            if (!IsActive)
            {
                return;
            }

            ComponentAvatar avatar = _rig.Avatar(_focus.ComponentId);
            if (avatar == null)
            {
                return;
            }

            if (!TryGetWorldBounds(avatar, out Bounds bounds))
            {
                return;
            }

            Vector3 eye = _viewer.EyePosition;
            if (_approachDirection == Vector3.zero)
            {
                // No direction was captured (focus opened before a viewer
                // existed, or the avatar had no bounds yet): fall back to the
                // current eye, but only for this frame — never persist it.
                Vector3 fallback = eye - bounds.center;
                fallback.y = 0f;
                if (fallback.sqrMagnitude > 0.01f)
                {
                    _approachDirection = fallback.normalized;
                }
                else
                {
                    return;
                }
            }

            Vector3 outward = _approachDirection;
            float distance = FramingDistance(bounds);
            Vector3 position = bounds.center + outward * distance;

            // Stay on the side of the machine the viewer is already on, but never
            // below the ground plane: the drivetrain sits 80 m up and a low angle
            // would bury the camera in the terrain.
            position.y = Mathf.Max(position.y, 1f + _viewer.Height);

            LateUpdateTicks++;
            LastBoundsCenter = bounds.center;
            LastFramingDistance = distance;
            LastTargetPosition = position;
            _viewer.AutoFlyTo(position, bounds.center);
        }

        /// <summary>
        /// Fly home, then hand control back. The flight is not left running after
        /// arrival: it would keep chasing a stale target and fight the keyboard.
        /// </summary>
        private void TickReturn()
        {
            if (_viewer == null || !_viewer.IsAutoFlying)
            {
                _returning = false;
                return;
            }

            if (Vector3.Distance(_viewer.transform.position, _returnPose.Value.Position) > 0.5f)
            {
                return;
            }

            _viewer.AutoFlyTo(_returnPose.Value.Position, _returnPose.Value.LookAt);
            _viewer.EndAutoFly();
            _returning = false;
            _returnPose = null;
            _approachDirection = Vector3.zero;
        }

        /// <summary>
        /// Union of the avatar's renderer bounds in world space. Renderer bounds
        /// are used rather than the transform because every avatar is an assembly
        /// whose parts hang off the component root at different offsets.
        /// </summary>
        private static bool TryGetWorldBounds(ComponentAvatar avatar, out Bounds bounds)
        {
            bounds = new Bounds(avatar.transform.position, Vector3.zero);
            bool any = false;
            foreach (Renderer child in avatar.GetComponentsInChildren<Renderer>())
            {
                if (child == null)
                {
                    continue;
                }

                if (!any)
                {
                    bounds = child.bounds;
                    any = true;
                }
                else
                {
                    bounds.Encapsulate(child.bounds);
                }
            }

            return any;
        }

        /// <summary>
        /// Distance at which a sphere of the component's radius fills
        /// <c>_fill</c> of the frame. The horizontal field of view is solved at a
        /// conservative 4:3 so the framing also holds on a narrower window.
        /// </summary>
        private float FramingDistance(Bounds bounds)
        {
            float radius = Mathf.Min(bounds.extents.magnitude, _maxRadius);
            float verticalFov = _camera != null ? _camera.fieldOfView : 60f;

            float horizontalFov = 2f * Mathf.Atan(
                Mathf.Tan(verticalFov * 0.5f * Mathf.Deg2Rad) * _conservativeAspect) * Mathf.Rad2Deg;

            float byHeight = radius / Mathf.Tan(verticalFov * 0.5f * Mathf.Deg2Rad);
            float byWidth = radius / Mathf.Tan(horizontalFov * 0.5f * Mathf.Deg2Rad);

            return Mathf.Max(_minDistance, Mathf.Max(byHeight, byWidth) / _fill + radius);
        }
    }
}