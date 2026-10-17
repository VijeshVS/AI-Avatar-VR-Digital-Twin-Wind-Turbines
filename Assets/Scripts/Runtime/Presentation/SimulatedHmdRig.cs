using UnityEngine;
using UnityEngine.InputSystem;

namespace Vrar.Presentation
{
    /// <summary>
    /// Desktop stand-in for the XR Device Simulator: a headset that can be
    /// flown around and looked with on a flat screen. Independent of the XR
    /// packages, so the PoC runs with no headset and no XR runtime.
    ///
    /// Controls: WASD to move, Q/E down/up, right-mouse drag to look, shift to
    /// move faster. An auto-flight (focus mode) takes over position and aim until
    /// the viewer touches the controls again, at which point manual flight
    /// resumes from wherever the flight left it.
    /// </summary>
    [RequireComponent(typeof(CharacterController))]
    public sealed class SimulatedHmdRig : MonoBehaviour
    {
        [SerializeField, Min(0.1f)] private float _walkSpeed = 12f;
        [SerializeField, Min(0.1f)] private float _runMultiplier = 3f;
        [SerializeField, Min(0.01f)] private float _lookSensitivity = 0.15f;
        [SerializeField, Min(1f)] private float _height = 1.7f;
        [SerializeField, Min(0.1f)] private float _autoFlySpeed = 60f;
        [SerializeField, Min(0.1f)] private float _autoTurnSpeed = 420f;
        [SerializeField] private Transform _head;

        private CharacterController _controller;
        private Vector2 _lookDelta;
        private float _yaw;
        private float _pitch;

        private bool _autoFlying;
        private Vector3 _autoPosition;
        private Vector3 _autoLookAt;

        /// <summary>
        /// The simulated headset. Assign a head at edit time to parent the camera
        /// to it, so looking up and down rotates the view.
        /// </summary>
        public Transform Head
        {
            get => _head;
            set => _head = value;
        }

        /// <summary>Standing eye height above the rig's feet.</summary>
        public float Height => _height;

        public bool IsAutoFlying => _autoFlying;
        public Vector3 EyePosition => transform.position + Vector3.up * _height;

        /// <summary>
        /// Where the viewer is standing and what it is aimed at. Focus mode saves
        /// this on the way in so clearing focus can put the camera back exactly
        /// where it was, instead of leaving it parked on the drive train.
        /// </summary>
        public CameraPose CapturePose()
        {
            return new CameraPose
            {
                Position = transform.position,
                LookAt = transform.position + transform.rotation * Vector3.forward * 100f
            };
        }

        /// <summary>
        /// Hand position and aim to an auto-flight. Safe to call every frame:
        /// the target moves (the rotor turns), so the caller re-issues it and the
        /// rig keeps converging rather than snapping once and drifting off.
        /// </summary>
        public void AutoFlyTo(Vector3 position, Vector3 lookAt)
        {
            _autoPosition = position;
            _autoLookAt = lookAt;
            _autoFlying = true;
        }

        public void EndAutoFly()
        {
            _autoFlying = false;
        }

        /// <summary>A camera position and the point it is aimed at.</summary>
        public struct CameraPose
        {
            public Vector3 Position;
            public Vector3 LookAt;
        }

        private void Awake()
        {
            _controller = GetComponent<CharacterController>();
            _controller.height = _height;
            _controller.center = new Vector3(0f, _height / 2f, 0f);

            if (_head == null)
            {
                GameObject head = new GameObject("Head");
                head.transform.SetParent(transform, false);
                head.transform.localPosition = new Vector3(0f, _height, 0f);
                _head = head.transform;
            }

            // Adopt the authored view. ReadLook() rebuilds the rotation every
            // frame from _yaw/_pitch, so starting them at zero would snap a camera
            // that the scene had pointed at the machine's upper half down to the
            // horizon, and anything above the frame centre would be lost.
            Vector3 body = transform.eulerAngles;
            _yaw = body.y;
            _pitch = NormaliseAngle(body.x) + NormaliseAngle(_head.localEulerAngles.x);
        }

        private static float NormaliseAngle(float degrees)
        {
            return degrees > 180f ? degrees - 360f : degrees < -180f ? degrees + 360f : degrees;
        }

        private void Update()
        {
            ReadMove();
            if (_autoFlying)
            {
                FlyTowardTarget();
            }

            ReadLook();
        }

        /// <summary>
        /// Converge on the auto-flight target at a bounded rate. Both axes are
        /// rate-limited rather than snapped, so switching focus reads as a camera
        /// move instead of a teleport.
        /// </summary>
        private void FlyTowardTarget()
        {
            Vector3 delta = _autoPosition - transform.position;
            float distance = delta.magnitude;
            if (distance > 0.01f)
            {
                float step = Mathf.Min(distance, _autoFlySpeed * Time.deltaTime);
                _controller.Move(delta / distance * step);
            }

            Vector3 toTarget = _autoLookAt - EyePosition;
            if (toTarget.sqrMagnitude < 0.0001f)
            {
                return;
            }

            Vector3 direction = toTarget.normalized;
            float targetYaw = Mathf.Atan2(direction.x, direction.z) * Mathf.Rad2Deg;
            float targetPitch = -Mathf.Asin(Mathf.Clamp(direction.y, -1f, 1f)) * Mathf.Rad2Deg;

            float maxStep = _autoTurnSpeed * Time.deltaTime;
            _yaw = Mathf.MoveTowardsAngle(_yaw, targetYaw, maxStep);
            _pitch = Mathf.MoveTowards(_pitch, targetPitch, maxStep);
        }

        private void ReadLook()
        {
            Mouse mouse = Mouse.current;
            if (mouse != null && mouse.rightButton.isPressed)
            {
                _lookDelta += mouse.delta.ReadValue() * 0.05f;
            }

            _yaw += _lookDelta.x * _lookSensitivity;
            _pitch = Mathf.Clamp(_pitch - _lookDelta.y * _lookSensitivity, -85f, 85f);
            transform.localRotation = Quaternion.Euler(0f, _yaw, 0f);

            if (_head != null)
            {
                _head.localRotation = Quaternion.Euler(_pitch, 0f, 0f);
            }

            _lookDelta = Vector2.Lerp(_lookDelta, Vector2.zero, Time.deltaTime * 8f);
        }

        private void ReadMove()
        {
            Keyboard keyboard = Keyboard.current;
            if (keyboard == null)
            {
                return;
            }

            Vector3 input = Vector3.zero;
            if (keyboard.wKey.isPressed)
            {
                input.z += 1f;
            }

            if (keyboard.sKey.isPressed)
            {
                input.z -= 1f;
            }

            if (keyboard.aKey.isPressed)
            {
                input.x -= 1f;
            }

            if (keyboard.dKey.isPressed)
            {
                input.x += 1f;
            }

            if (keyboard.eKey.isPressed)
            {
                input.y += 1f;
            }

            if (keyboard.qKey.isPressed)
            {
                input.y -= 1f;
            }

            if (input == Vector3.zero)
            {
                return;
            }

            // Touching the controls hands control back to the viewer. Focus mode
            // keeps its selection in the HUD; it just stops flying the camera.
            _autoFlying = false;

            float speed = _walkSpeed * (keyboard.leftShiftKey.isPressed ? _runMultiplier : 1f);
            Vector3 world = transform.TransformDirection(input.normalized) * speed;
            _controller.Move(world * Time.deltaTime);
        }

#if UNITY_EDITOR
        private void OnDrawGizmos()
        {
            if (_head == null)
            {
                return;
            }

            Gizmos.color = new Color(0.2f, 0.8f, 1f, 0.9f);
            Gizmos.DrawWireSphere(_head.position, 0.12f);
            Gizmos.DrawLine(_head.position, _head.position + _head.forward * 0.4f);
        }
#endif
    }
}