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
    /// move faster.
    /// </summary>
    [RequireComponent(typeof(CharacterController))]
    public sealed class SimulatedHmdRig : MonoBehaviour
    {
        [SerializeField, Min(0.1f)] private float _walkSpeed = 12f;
        [SerializeField, Min(0.1f)] private float _runMultiplier = 3f;
        [SerializeField, Min(0.01f)] private float _lookSensitivity = 0.15f;
        [SerializeField, Min(1f)] private float _height = 1.7f;
        [SerializeField] private Transform _head;

        private CharacterController _controller;
        private Vector2 _lookDelta;
        private float _yaw;
        private float _pitch;

        public Transform Head => _head;

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

            _yaw = transform.eulerAngles.y;
        }

        private void Update()
        {
            ReadLook();
            ReadMove();
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